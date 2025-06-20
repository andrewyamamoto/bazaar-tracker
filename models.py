from tortoise import fields
from tortoise.models import Model

class Game(Model):
    id = fields.IntField(pk=True)
    # player = fields.CharField(max_length=255)
    player = fields.ForeignKeyField('models.Users', related_name='games')
    season = fields.IntField()
    # patch = fields.ForeignKeyField('models.Patches', related_name='games')
    patch_id = fields.CharField(max_length=255)
    ranked = fields.BooleanField()
    hero = fields.CharField(max_length=255)
    wins = fields.IntField()
    finished = fields.IntField()
    media = fields.CharField(max_length=2000)
    notes = fields.TextField(max_length=2000)
    played = fields.DatetimeField(max_length=2000, generated=True)
    upload = fields.CharField(max_length=2000)

class Users(Model):
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=150, unique=True)
    password = fields.CharField(max_length=255)

class Patches(Model):
    id = fields.IntField(pk=True)
    version = fields.CharField(max_length=150, unique=True)

class SeasonValue:
    def __init__(self, default):
        self._value = default

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
