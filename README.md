# tgbot
thats a bot for handeling 3d printing for big projects
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Python и Git
sudo apt install -y python3 python3-pip python3-venv git


# Клонирование репозитория
cd ~
git clone https://github.com/ТВОЙ_НИК/print3d-bot.git
cd print3d-bot

# Создание виртуального окружения
python3 -m venv venv
source venv/bin/activate

# Установка зависимостей
pip install -r requirements.txt

#запуск 
python3 bot.py
