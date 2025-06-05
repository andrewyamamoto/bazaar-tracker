#!/usr/bin/env python3
from typing import List
import models
from tortoise import Tortoise
from nicegui import app, ui
import time
import psycopg2
import sys


async def init_db() -> None:
    await Tortoise.init(db_url='asyncpg://postgres:postgres@localhost:5432/bazaar', modules={'models': ['models']})
    #await Tortopip install tortoise-orm[psycopg]ise.generate_schemas()


async def close_db() -> None:
    await Tortoise.close_connections()

app.on_startup(init_db)
app.on_shutdown(close_db)


@ui.refreshable
async def list_of_games() -> None:
    async def delete(games: models.Game) -> None:
        await games.delete()
        list_of_games.refresh()

    games: List[models.Game] = await models.Game.all()
    for game in reversed(games):
        with ui.card():
            with ui.row().classes('items-left'):
                #ui.input('Player').bind_value(game,'player')
                ui.label().bind_text_from(game, 'player')
                ui.label().bind_text_from(game, 'season')
                ui.label().bind_text_from(game, 'ranked')
                ui.label().bind_text_from(game, 'hero')
                ui.label().bind_text_from(game, 'wins')
                ui.label().bind_text_from(game, 'finished')
                ui.label().bind_text_from(game, 'media')
                ui.label().bind_text_from(game, 'notes')
                ui.label().bind_text_from(game, 'played')
                ui.button(icon='delete', on_click=lambda u=game: delete(u)).props('flat')






@ui.page('/')
async def index():
    async def create() -> None:
        await models.Game.create(
                player=player.value,
                season=season.value or 0,
                ranked=ranked.value,
                hero=hero.value,
                wins=wins.value,
                finished=finished.value,
                media=media.value,
                notes=notes.value,
                )
        player.value = ''
        season.value = None
        list_of_games.refresh()

    with ui.column().classes('mx-auto'):
        await list_of_games()
        #with ui.row().classes('w-full items-left px-4'):
        with ui.row():
            player = ui.input(label='Player')
            season = ui.number(label='Season', format='%.0f')
            ranked = ui.checkbox()
            hero = ui.input(label='Hero')
            wins = ui.number(label='Wins')
            finished = ui.number(label='Finished')
            media = ui.input(label='Media')
            notes = ui.input(label='Notes')
            ui.button(on_click=create, icon='add').props('flat').classes('ml-auto')


ui.run()
