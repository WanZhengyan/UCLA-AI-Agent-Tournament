#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -r requirements.txt pyinstaller==6.22.3
.build-venv/bin/python -m PyInstaller --clean --noconfirm --onefile --strip --name PokemonChampion --paths . --collect-submodules mcp.client --collect-data mcp --copy-metadata mcp --hidden-import competition_agent --collect-submodules redalert_bot --collect-submodules werewolf_bot --collect-submodules hok_platform_bot --hidden-import pokemon_bot.agent --hidden-import pokemon_bot.battle --hidden-import pokemon_bot.draft --hidden-import pokemon_bot.selftest --hidden-import socksio --exclude-module numpy --exclude-module PIL --exclude-module zstandard --exclude-module matplotlib --exclude-module pandas --exclude-module scipy --exclude-module pytest --exclude-module IPython --exclude-module tkinter --add-data pokemon_bot/dex_data.json:pokemon_bot exe_entry.py
./dist/PokemonChampion --self-test
