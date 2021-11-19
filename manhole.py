# manhole - A maubot plugin that provides a Python shell to access the internals of maubot
# Copyright (C) 2021 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Type, Set, Callable, Optional
import asyncio
import sys
import os

from attr import dataclass

from mautrix.util.manhole import start_manhole
from mautrix.types import UserID
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
from mautrix import __version__ as __mautrix_version__
from maubot import Plugin, MessageEvent, __version__
from maubot.handlers import command
from maubot.client import Client
from maubot.instance import PluginInstance


@dataclass
class ManholeState:
    server: asyncio.AbstractServer
    opened_by: UserID
    close: Callable[[], None]
    whitelist: Set[int]


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("users")
        helper.copy("path")


class ManholeBot(Plugin):
    config: Config
    state: Optional[ManholeState]

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    async def start(self) -> None:
        self.config.load_and_update()
        self.state = None

    async def stop(self) -> None:
        if self.state:
            self.state.close()

    def get_banner(self, opened_by: str) -> str:
        return (f"Python {sys.version} on {sys.platform}\n"
                f"maubot {__version__} with mautrix-python {__mautrix_version__}\n"
                f"Manhole opened by {opened_by}\n")

    def get_global_namespace(self) -> dict:
        return {
            "client": self.client,
            "http": self.http,
            "loop": self.loop,
            "manhole": self.state,
            "Client": Client,
            "PluginInstance": PluginInstance,
        }

    @command.new(name="manhole", help="Open the manhole")
    async def manhole(self, evt: MessageEvent) -> None:
        try:
            uid = self.config["users"][evt.sender]
        except KeyError:
            await evt.reply("You're not whitelisted to use the manhole")
            return
        if self.state:
            await evt.reply(f"There's an existing manhole opened by {self.state.opened_by}.")
            return
        whitelist = {uid}
        path = self.config["path"]
        server, close = await start_manhole(path=path, banner=self.get_banner(evt.sender),
                                            namespace=self.get_global_namespace(),
                                            loop=self.loop, whitelist=whitelist)
        self.state = ManholeState(server=server, opened_by=evt.sender, close=close,
                                  whitelist=whitelist)
        self.log.info(f"{evt.sender} opened a manhole")
        await evt.reply(f"Opened manhole at unix://{path} with UID {uid} whitelisted")
        await server.wait_closed()
        self.state = None
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        self.log.info(f"{evt.sender}'s manhole was closed")
        await evt.reply("Your manhole was closed.")
