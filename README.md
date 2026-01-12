# tgbot
thats a bot for handeling 3d printing for big projects
# Обновление системы и установка Python и Git

Debian/Ubuntu/остальные основанные на них:
```
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git
```
Arch/основанные на нём:
```
sudo pacman -Syu git python python-pip python3-venv git
```
# Клонирование репозитория
```
cd ~
git clone https://github.com/ТВОЙ_НИК/print3d-bot.git
cd print3d-bot
```
# Создание виртуального окружения
```
python3 -m venv venv
source venv/bin/activate
```
# Установка зависимостей
```
pip install -r requirements.txt
```
#запуск 
```
python3 bot.py
```
