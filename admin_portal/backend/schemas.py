"""Validated request bodies for the admin API."""
from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Login(Input):
    username: str = Field(max_length=200)
    password: str = Field(max_length=128)


class Password(Input):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


class Room(Input):
    code: str = Field(pattern=r'^[0-9]{6,8}$')
    name: str = Field(min_length=1, max_length=100)
    blocked: bool = False


class NewRoom(Room):
    host_pin: str = Field(pattern=r'^[0-9]{4,16}$')
    viewer_pin: str = Field(pattern=r'^[0-9]{4,16}$')


class User(Input):
    room_id: str
    name: str = Field(min_length=1, max_length=100)
    role: str = Field(pattern=r'^(host|viewer)$')
    blocked: bool = False
    pin: str | None = Field(default=None, pattern=r'^[0-9]{4,16}$')


class Confirm(Input):
    confirmation: str


class Command(Input):
    action: str = Field(pattern=r'^(play|pause|sync)$')


