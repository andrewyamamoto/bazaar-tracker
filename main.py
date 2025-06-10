#!/usr/bin/env python3
import bcrypt
import boto3
import hashlib
import httpx
import json
import models
import os
import re
import time
import uvicorn

from dotenv import load_dotenv
from nicegui import app, ui, context
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from tortoise import Tortoise
from tortoise.expressions import Q
from types import SimpleNamespace

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

load_dotenv()

DATABASE_HOST = os.getenv("DB_HOST")
DATABASE_PORT = os.getenv("DB_PORT", "5432")
DATABASE_NAME = os.getenv("DB_NAME")
DATABASE_USER = os.getenv('DB_USER')
DATABASE_PASSWORD = os.getenv('DB_PASSWORD')
BUCKET_UPLOAD_URL = os.getenv('BUCKET_UPLOAD_URL')
BUCKET_KEY = os.getenv('BUCKET_KEY')
BUCKET_SECRET = os.getenv('BUCKET_SECRET')
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'
SESSION_SECRET = os.getenv('SESSION_SECRET')



async def init_db():
    # db_url = f"postgres://{DATABASE_USER}:{DATABASE_PASSWORD}@db-postgresql-sfo2-10284-do-user-282100-0.m.db.ondigitalocean.com:25060/bazaar"
    db_url = f"postgres://{DATABASE_USER}:{DATABASE_PASSWORD}@{DATABASE_HOST}:{DATABASE_PORT}/{DATABASE_NAME}"
    await Tortoise.init(
        db_url=db_url,
        modules={"models": ["models"]}
    )
    await Tortoise.generate_schemas(safe=True)

async def close_db():
    if Tortoise._inited:
        await Tortoise.close_connections()

app.on_startup(init_db)
app.on_shutdown(close_db)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)


async def generate_presigned_post(filename):
    session = boto3.session.Session()
    client = session.client('s3',
        region_name='nyc3',
        endpoint_url=BUCKET_UPLOAD_URL,
        aws_access_key_id=BUCKET_KEY,
        aws_secret_access_key=BUCKET_SECRET)

    return client.generate_presigned_post(
        Bucket='bazaar-files',
        Key=f'screenshots/{filename}',
        Fields={"acl": "public-read"},
        Conditions=[
            {"acl": "public-read"},
            ["starts-with", "$Content-Type", ""]
        ],
        ExpiresIn=3600
    )

async def create_user(username, password):
    existing = await models.Users.get_or_none(Q(username=username))
    if existing:
        return False, "User already exists."
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    await models.Users.create(username=username, password=hashed)
    return True, "User created successfully."

async def get_current_user():
    session = getattr(context, 'session', None)
    if not session:
        return None
    user_id = session.get('user_id')
    if not user_id:
        return None
    user = await models.Users.get_or_none(id=user_id)
    return user

async def authenticate(username, password):
    user = await models.Users.get_or_none(Q(username=username))
    if user and bcrypt.checkpw(password.encode(), user.password.encode()):
        return user
    return None

@app.post('/api/login')
async def api_login(request: Request):
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    user = await authenticate(username, password)
    if user:
        request.session['user_id'] = user.id
        latest_game = await models.Game.filter(player=user.id).order_by('-season').first()
        latest_season = latest_game.season if latest_game else 3
        return {'success': True, 'redirect': f'/dashboard/{latest_season}'}
    return {'success': False, 'error': 'Invalid email or password.'}

@ui.page('/')
def login_page(request: Request):
    context.session = request.session
    ui.page_title("Bazaar Tracker")
    ui.label('Login').classes('text-3xl font-bold mb-4')
    email = ui.input('Username').props('type=text').classes('w-full max-w-sm')
    password = ui.input('Password').props('type=password').classes('w-full max-w-sm')
    message = ui.label('').classes('text-red-500 mt-2')

    async def handle_login():
        if not email.value or not password.value:
            message.text = 'Username and password cannot be blank.'
            return
        payload = {"username": email.value, "password": password.value}
        result = await ui.run_javascript(
            f"return fetch('/api/login', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({json.dumps(payload)})}}).then(r => r.json())"
        )
        if result.get('success'):
            message.text = ''
            ui.navigate.to(result.get('redirect', '/dashboard/0'))
        else:
            message.text = 'Invalid email or password.'

    async def handle_signup():
        if not email.value or not password.value:
            message.text = 'Username and password cannot be blank.'
            return
        success, msg = await create_user(email.value, password.value)
        message.text = msg
        if success:
            ui.notify('Account created! Please log in.', color='positive')

    with ui.row().classes('mt-4 gap-2'):
        ui.button('Login', on_click=handle_login).classes('bg-blue-600 text-white px-4 py-2 rounded')
        ui.button('Sign Up', on_click=handle_signup).classes('bg-green-600 text-white px-4 py-2 rounded')

@ui.page('/logout')
async def logout_page(request: Request):
    context.session = request.session
    context.session.clear()
    ui.navigate.to('/')

@ui.refreshable
async def list_of_games(page_number=1, page_size=8, session=None, season=None) -> None:
    context.session = session or getattr(context, 'session', None)
    context.season = season if season is not None else getattr(context, 'season', 0)
    async def delete_game(game_id: int) -> None:
        # ensure that the game belongs to the current user before deleting
        user = await get_current_user()
        game = await models.Game.get_or_none(id=game_id, player=user.id)
        if not game:
            ui.notify('Unauthorized', color='negative')
            return
        await game.delete()
        list_of_games.refresh(page_number=page_number, session=context.session, season=context.season)

    user = await get_current_user()
    if not user:
        ui.label('Not logged in').classes('text-red-500')
        ui.navigate.to('/')
        return

    season = context.season

    total_games = await models.Game.filter(player=user.id, season=season).count()
    games = await models.Game.filter(player=user.id, season=season)\
        .order_by('-played')\
        .offset((page_number - 1) * page_size)\
        .limit(page_size)\
        .prefetch_related('player')

    total_pages = max((total_games + page_size - 1) // page_size, 1)

    grid_style = (
        'display: grid; '
        'grid-template-columns: repeat(9, minmax(100px, 1fr)); '
        'gap: 0.5rem; align-items: center; width: 100%;'
    )

    with ui.column().classes('w-full'):
        with ui.element('div').style(grid_style).classes('font-bold'):
            for header in ['Player', 'Hero', 'Mode', 'Win/Day', 'Media', 'Upload', 'Notes', 'Played', 'Actions']:
                ui.label(header).classes('truncate text-center')

        for game in games:
            username = game.player.username
            placement_color = (
                "text-white" if game.wins == 10 and game.finished == 10 else  # Perfect (Diamon)
                "text-yellow-400" if game.wins == 10 and game.finished > 10 else    # Gold
                "text-gray-400" if game.wins >= 7 else                            # Silver
                "text-[#cd7f32]" if game.wins >= 4 else                           # Bronze
                "text-gray-500"
            )
            hero_colors = {
                'Dooley': 'bg-[#397d83] text-white',
                'Mak': 'bg-[#2da337] text-white',
                'Pygmalien': 'bg-[#f56a1f] text-white',
                'Vanessa': 'bg-[#6312de] text-white',
            }
            hero_class = hero_colors.get(game.hero.lower().capitalize(), 'bg-gray-200 text-gray-900')

            with ui.element('div').style(grid_style):
                ui.label(username).classes('truncate text-center')
                ui.label(game.hero).classes(
                    f'truncate rounded-full px-3 py-1 {hero_class} text-sm font-semibold shadow text-center'
                )
                ui.label("Ranked" if game.ranked else "Non-Ranked").classes('truncate text-center')
                ui.label("Perfect Game" if game.wins == 10 and game.finished == 10 else f"{game.wins}/{game.finished}").classes(
                    f'truncate {placement_color} text-center')
                ui.link('View', target=game.media, new_tab=True).classes('text-blue-600 underline text-center') if game.media else ui.label('-').classes('truncate text-center text-gray-500')

                with ui.dialog().props('maximized') as dialog, ui.card().classes('w-full h-full'):
                    ui.image(game.upload).props('fit=none').classes('mb-4')
                    ui.button('Close', on_click=dialog.close).classes('mt-2')

                ui.link('View').on('click', lambda d=dialog: d.open()).classes('text-blue-600 underline text-center') if game.upload else ui.label('No Upload').classes('truncate text-gray-500 text-center')

                ui.label(game.notes or '').classes('truncate text-center')
                played_str = game.played.strftime('%Y-%m-%d %I:%M %p') if game.played else ''
                ui.label(played_str).classes('truncate text-center')
                ui.button(icon="delete", on_click=lambda g=game.id: delete_game(g)).props('color=negative flat')
                ui.separator().classes('col-span-9 my-1')

        # Pagination controls
        with ui.row().classes('justify-center mt-4'):
            if page_number > 1:
                ui.button('Previous', on_click=lambda: list_of_games.refresh(page_number=page_number - 1, session=context.session, season=context.season))
            ui.label(f'Page {page_number} of {total_pages}').classes('mt-2')
            if page_number < total_pages:
                ui.button('Next', on_click=lambda: list_of_games.refresh(page_number=page_number + 1, session=context.session, season=context.season))
    
    # Placement tally chart for each hero

    # Fetch placement data for the current user and season
    games_for_chart = await models.Game.filter(player=user.id, season=season).all()

    # Prepare data: {hero: [count of 0 wins, 1 win, ..., 10 wins]}
    hero_options = ['Dooley', 'Mak', 'Pygmalien', 'Vanessa']
    placement_counts = {hero: [0]*11 for hero in hero_options}

    for game in games_for_chart:
        hero = game.hero.lower().capitalize()
        if hero in placement_counts and 0 <= game.wins <= 10:
            placement_counts[hero][game.wins] += 1

    # Chart data
    labels = [str(i) for i in range(11)]
    datasets = [
        {
            "label": hero,
            "data": placement_counts[hero],
        }
        for hero in hero_options
    ]
    ui.label('Game Stats').classes('font-bold text-2xl mb-2 text-grey-200 w-full mt-2').style('border-top: 2px solid #444; padding-top: 1rem;')
    with ui.row().classes('w-full mb-4 gap-4 flex flex-wrap items-start'):
        # Ranked placement tally
        with ui.card().classes('w-full sm:w-[48%] min-w-[300px]'):

            placement_categories = ['No Placement', 'Bronze', 'Silver', 'Gold', 'Perfect']
            placement_counts_by_category = {hero: [0, 0, 0, 0, 0] for hero in hero_options}

            for game in games_for_chart:
                if not game.ranked:
                    continue  # Only count ranked games
                hero = game.hero.lower().capitalize()
                if hero not in placement_counts_by_category:
                    continue
                if game.wins == 10 and game.finished == 10:
                    placement_counts_by_category[hero][4] += 1  # Perfect
                elif 8 <= game.wins <= 10 and game.finished > 10:
                    placement_counts_by_category[hero][3] += 1  # Gold
                elif 4 <= game.wins <= 7:
                    placement_counts_by_category[hero][2] += 1  # Silver
                elif 1 <= game.wins <= 3:
                    placement_counts_by_category[hero][1] += 1  # Bronze
                else:
                    placement_counts_by_category[hero][0] += 1  # No Placement

            columns = [
                {"name": "placement", "label": "Placement", "field": "placement", "align": "left"},
            ] + [
                {"name": hero, "label": hero, "field": hero, "align": "center"}
                for hero in hero_options
            ]
            rows = []
            for idx, category in enumerate(placement_categories):
                row = {"placement": category}
                for hero in hero_options:
                    row[hero] = placement_counts_by_category[hero][idx]
                rows.append(row)

            ui.label('Ranked Placement').classes('font-bold mb-2')
            with ui.element('div').classes('overflow-x-auto w-full'):
                with ui.table(columns=columns, rows=rows).classes('w-full text-center rounded-lg border border-gray-700'):
                    pass

        # Unranked placement tally
        with ui.card().classes('w-full sm:w-[48%] min-w-[300px]'):

            unranked_counts_by_category = {hero: [0, 0, 0, 0, 0] for hero in hero_options}

            for game in games_for_chart:
                if game.ranked:
                    continue  # Only count unranked games
                hero = game.hero.lower().capitalize()
                if hero not in unranked_counts_by_category:
                    continue
                if game.wins == 10 and game.finished == 10:
                    unranked_counts_by_category[hero][4] += 1  # Perfect
                elif 8 <= game.wins <= 10 and game.finished > 10:
                    unranked_counts_by_category[hero][3] += 1  # Gold
                elif 4 <= game.wins <= 7:
                    unranked_counts_by_category[hero][2] += 1  # Silver
                elif 1 <= game.wins <= 3:
                    unranked_counts_by_category[hero][1] += 1  # Bronze
                else:
                    unranked_counts_by_category[hero][0] += 1  # No Placement

            unranked_rows = []
            for idx, category in enumerate(placement_categories):
                row = {"placement": category}
                for hero in hero_options:
                    row[hero] = unranked_counts_by_category[hero][idx]
                unranked_rows.append(row)

            ui.label('Unranked Placement').classes('font-bold mb-2')
            with ui.element('div').classes('overflow-x-auto w-full'):
                with ui.table(columns=columns, rows=unranked_rows).classes('w-full text-center rounded-lg border border-gray-700'):
                    pass

        # def update():
        #     grid.options['rowData'][0]['age'] += 1
        #     grid.update()
        

@ui.page('/dashboard/{season_id}')
async def index(request: Request, season_id: str = None):

    context.session = request.session
    
    ui.page_title("Bazaar Tracker")
    season_source = season_id or context.query.get('season', '0')
    
    try:
        default_season = int(season_source)
    except ValueError:
        default_season = 0

    class SeasonValue:
        def __init__(self, default):
            self._value = default

        @property
        def value(self):
            return self._value

        @value.setter
        def value(self, v):
            self._value = v

    season = SeasonValue(default_season)
    context.season = season.value

    user = await get_current_user()
    if DEV_MODE and not user:
        user, _ = await models.Users.get_or_create(id=1, defaults={'username': 'devuser', 'password': 'placeholder'})
        context.session['user_id'] = user.id
    if not user:
        ui.navigate.to('/')
        return
    ui.label(f'Logged in as: {user.username}').classes('text-sm text-gray-500 mb-2')
        
    ui.button('Log Out', on_click=lambda: ui.navigate.to('/logout')).classes('absolute top-4 right-4 bg-red-600 text-white px-4 py-2 rounded')
    state = SimpleNamespace(uploaded_url='')
    
    async def handle_upload(e):

        if not e or not getattr(e, 'content', None):
            ui.notify('No file uploaded (optional)', color='warning')
            return

        try:
            folder = 'screenshots'
            original_name = e.name or "upload"
            hash_digest = hashlib.sha256((original_name + str(time.time())).encode()).hexdigest()[:16]
            _, ext = os.path.splitext(original_name)
            name = f"{hash_digest}{ext.lower()}"
            key = f"{folder}/{name}"
            
            presigned = await generate_presigned_post(name)
            fields = presigned['fields']
            data = fields.copy()
            files = {'file': (name, e.content, e.type or 'application/octet-stream')}

            async with httpx.AsyncClient() as client:
                resp = await client.post(presigned['url'], data=data, files=files)

            if resp.status_code in (200, 204):
                CUSTOM_CDN_BASE_URL = "https://bazaar-files.misterdroo.com"

                state.uploaded_url = f"{CUSTOM_CDN_BASE_URL}/{fields['key']}"
                ui.notify('Upload successful!')
            else:
                ui.notify('Upload failed!', color='negative')

        except Exception as ex:
            print('Upload exception:', ex)
            ui.notify('Unexpected error during upload', color='negative')

    async def create() -> None:

        await models.Game.create(
            player=player.value,
            season=season.value or 0,
            ranked=ranked.value,
            hero=hero.value,
            wins=wins.value,
            finished=finished.value,
            media=media.value,
            upload=state.uploaded_url,
            notes=notes.value,
        )
        ranked.value = False
        hero.value = None
        wins.value = 0
        finished.value = 0
        media.value = ''
        notes.value = ''
        state.uploaded_url = ''
        upload_component.reset()
        list_of_games.refresh(session=context.session, season=season.value)
        ui.notify('Run added!')
    
    with ui.column().classes('w-full'):
        ui.label('Bazaar Tracker').classes('text-3xl font-bold')
        ui.label(f'Current Season: {season.value}').classes('text-lg')
        
    with ui.row().classes('flex w-full gap-4'):

        with ui.column().classes('w-[400px] shrink-0'):
            with ui.row().classes('w-full gap-4'):
                
                class PlayerValue:
                    @property
                    def value(self):
                        return user
                    @value.setter
                    def value(self, v):
                        pass

                player = PlayerValue()
            
            
            with ui.row().classes('items-center gap-0'):
                ranked = ui.checkbox()
                ui.label('Ranked').bind_visibility_from(ranked, 'visible', lambda _: True)

            hero_options = ['Dooley', 'Mak', 'Pygmalien', 'Vanessa']
            with ui.row().classes('gap-4'):
                hero_checkboxes = []
                for h in hero_options:
                    cb = ui.checkbox(h, value=False)
                    hero_checkboxes.append(cb)

            def update_hero_selection(e):
                for cb in hero_checkboxes:
                    if cb != e.sender:
                        cb.value = False

            for cb in hero_checkboxes:
                cb.value = False
                cb.on('change', update_hero_selection)

            class HeroValue:
                @property
                def value(self):
                    for cb in hero_checkboxes:
                        if cb.value:
                            return cb.text
                    return None
                @value.setter
                def value(self, v):
                    for cb in hero_checkboxes:
                        cb.value = (cb.text == v)

            hero = HeroValue()

            wins = ui.slider(min=0, max=10, step=1, value=0).classes('w-full')
            wins_label = ui.label(f"Wins: {wins.value}")
            wins_label.bind_text_from(wins, "value", lambda v: f"Wins: {v}")

            finished = ui.slider(min=0, max=20, step=1, value=wins.value).classes('w-full')

            finished_label = ui.label(f"Day Finished: {finished.value}")
            finished_label.bind_text_from(finished, "value", lambda v: f"Day Finished: {v}")

            def enforce_win_limit(e=None):
                if wins.value > finished.value:
                    wins.value = finished.value
                if finished.value < wins.value:
                    finished.value = wins.value

            def sync_finished_with_wins(e=None):
                if finished.value < wins.value:
                    finished.value = wins.value

            wins.on('change', sync_finished_with_wins)
            wins.on('change', enforce_win_limit)
            finished.on('change', enforce_win_limit)
            def is_valid_url(url: str) -> bool:
                pattern = re.compile(
                    r'^(https?://)'                  
                    r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'  
                    r'(:\d+)?'                       
                    r'(/.*)?$'                       
                )
                return bool(pattern.match(url.strip()))

            with ui.element('div').classes('border border-gray-800 rounded-lg p-2 w-full pt-0'):
                media = ui.input(label='Media URL').classes('w-full')

            def validate_media_url():
                url = media.value or ''
                if url and not is_valid_url(url):
                    media.props('error error-message="Invalid Media URL"')
                else:
                    media.props(remove='error error-message')

            media.on('change', validate_media_url)
            upload_component = ui.upload(label='Upload Screenshot or Video', on_upload=handle_upload).classes('w-full')
            MAX_NOTES_LENGTH = 75
            notes = ui.textarea(label=f'Notes (max {MAX_NOTES_LENGTH} chars)').classes('w-full rounded-lg border border-gray-800 p-2 pt-0')
            char_count_label = ui.label('0/75').classes('text-xs text-gray-500 mb-2')

            def update_char_count():
                value = notes.value or ''
                if len(value) > MAX_NOTES_LENGTH:
                    value = value[:MAX_NOTES_LENGTH]
                    notes.value = value
                char_count_label.text = f'{len(value)}/{MAX_NOTES_LENGTH}'

            ui.timer(0.25, update_char_count)
            ui.button('Add Run', on_click=create).classes('w-full').props('color=primary')

        with ui.column().classes('flex-1'):
            await list_of_games(session=request.session, season=season.value)

    ui.run(dark="true")
