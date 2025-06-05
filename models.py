from tortoise import fields, models


class Game(models.Model):
    id = fields.IntField(pk=True)
    player = fields.CharField(max_length=255)
    season = fields.IntField()
    ranked = fields.BooleanField()
    hero = fields.CharField(max_length=255)
    wins = fields.IntField()
    finished = fields.IntField()
    media = fields.CharField(max_length=2000)
    notes = fields.TextField(max_length=2000)
    played = fields.DatetimeField(max_length=2000, generated=True)
