<div align="center">

# 🛡️ Liberal IP Roller
### Industrial-grade Multi-Cloud IP Rotation Engine

[![Release](https://img.shields.io/badge/Release-v0.2.1-success.svg)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Built with Textual](https://img.shields.io/badge/Built%20with-Textual-000000.svg)](https://github.com/Textualize/textual)
[![Stars](https://img.shields.io/github/stars/censorny/liberal-ip-roller?style=social)](https://github.com/censorny/liberal-ip-roller)

**Автоматизируйте поиск специфических IP-адресов с хирургической точностью и промышленной надежностью.**  
*Automate the search for specific IP ranges with surgical precision and industrial stability.*

---

### [🇷🇺 Читать на Русском](#russian) &nbsp; | &nbsp; [🇬🇧 Read in English](#english)

</div>

---

<a name="russian"></a>
## 🇷🇺 Русская Версия

> [!CAUTION]
> **⚠️ ВНИМАНИЕ / ATTENTION**  
> Проект предназначен для автоматизации облачных ресурсов. Перед запуском **ТЩАТЕЛЬНО** изучите настройки в `config.json` и лимиты ваших облачных провайдеров. Ротация ресурсов может быть платной в зависимости от вашего тарифа. Автор не несет ответственности за списания средств, превышение квот или блокировки аккаунтов. Изучайте документацию облаков перед стартом!

### 🎯 Возможности (Охуенные фичи)
**Liberal IP Roller** — это не просто скрипт, это полноценный комбайн для поиска нужных ("белых") IP-адресов.
- 🎩 **Industrial TUI**: Полноценный терминальный интерфейс с поддержкой мыши, горячих клавиш и красивой анимацией.
- 🛡️ **Graceful Shutdown**: Безопасная остановка процесса. Нажали `Ctrl+C` — программа корректно завершит потоки и ничего не оставит "висеть" в облаке.
- 📄 **Ротация Логов**: Все операции пишутся в `app_rolling.log` с ограничением по размеру. Ваш диск никогда не переполнится.
- 📱 **Уведомления**: Поддержка Telegram-бота. Как только нужный адрес будет пойман — скрипт пришлет сообщение.
- 🌍 **Мультиязычность**: Встроенный интерфейс как на русском, так и на английском.

---

### ☁️ Провайдеры

| Возможность | 🟡 Yandex Cloud | 🔵 Reg.ru |
| :--- | :--- | :--- |
| **Механика поиска** | Ротация статических адресов в VPC | Полное пересоздание VM (Instance) |
| **Авторизация** | Service Account Key (JSON) / IAM | API Token |
| **Скорость** | ⚡ Очень быстро (пара секунд) | 🕒 Умеренно (1-2 минуты на сервер) |
| **Для чего идеально?** | Агрессивная, непрерывная стабильная ротация. | Поиск специфических пулов (например, Москва) и другие гео. |

---

### 📖 Подробный Гайд по запуску

#### Шаг 1: Подготовка
Убедитесь, что у вас установлен Python версии >= **3.10**. 
Склонируйте репозиторий:
```bash
git clone https://github.com/censorny/liberal-ip-roller/
cd liberal-ip-roller
pip install -r requirements.txt
```

#### Шаг 2: Настройка `config.json`
Откройте `config.json` в любом текстовом редакторе. Это конфигурационный файл, который контролирует всё.

**Для Yandex Cloud:**
* Самый надежный способ работы — создать Сервисный Аккаунт (Service Account) в консоли Яндекса, выдать ему роль `editor` на ваш каталог (folder), создать для него "Авторизованный ключ" и сохранить скачанный `.json` файл себе на компьютер.
* В `config.json` в блоке `yandex.api.folder_id` вставьте ID вашего каталога.
* В `yandex.api.sa_key_path` вставьте абсолютный путь к вашему ключу (например, `C:\\keys\\sa_key.json`). IAM токен останется пустым, скрипт будет генерировать его сам!

**Для Reg.ru:**
* Получите API-токен в панели управления Cloud VPS.
* Вставьте его в `config.json` в поле `regru.api.api_token`.

**Настройка пулов IP:**
В секциях `yandex.process.allowed_ranges` и `regru.process.allowed_ranges` укажите подсети (в формате CIDR), которые вы ищете. Например: `"84.201.128.0/18"`.

#### Шаг 3: Запуск и Использование
Запустите приложение:
```bash
python main.py
# или используйте run.bat (Windows) / run.sh (Linux/Mac)
```

1. **Выбор провайдера**: На старте система попросит выбрать, где вы хотите искать IP.
2. **Dashboard**: Попав в главный экран, нажмите `Старт (Start)`. Скрипт начнет автоматическую ротацию. 
3. **Мониторинг**: В реальном времени вы будете видеть ошибки API, лог действий и количество попыток.
4. **Успех**: При успешном нахождении адреса скрипт автоматически остановится. Вы сможете закрепить адрес в консоли провайдера.

---

### 💖 Поддержать Проект
Если этот проект сэкономил вам кучу нервов, времени или денег на прокси, можете занести автору на кофе. Буду очень признателен за поддержку Open Source:

| Валюта | Сеть | Адрес кошелька |
| :--- | :--- | :--- |
| **USDT** | **TON** | `UQAStmfLsz9c3yRA3SeADT5kKdKSUZIt0i6z6B0A6gT884wE` |
| **USDT** | **TRC20** | `THCFoTpjGdaEkGvQe9V8A3WMdQMJ3fUhTq` |
| **USDT** | **SPL (Solana)** | `E1Z978yBMJ3UA4y7xZwv57cBxEUoZ5i9TMsrhcxfVRV6` |
| **USDT** | **ERC20** | `0xc6e0828F6aAF152E82fbEb9f7Abd39051208502F` |
| **USDT** | **BEP20** | `0xc6e0828F6aAF152E82fbEb9f7Abd39051208502F` |

---
---

<a name="english"></a>
## 🇬🇧 English Version

> [!CAUTION]
> **⚠️ ATTENTION / ВНИМАНИЕ**  
> This project automates cloud resources. Before running, **CAREFULLY** study the settings in your `config.json` and the limits of your cloud providers. Rolling resources might cost money depending on your billing plan. The author is not responsible for any costs incurred, quota exceedings, or account suspensions. Review your cloud documentation before hitting start!

### 🎯 Key Features (Fucking Awesome Highlights)
**Liberal IP Roller** is not just a script; it's a full-fledged combine for finding specific ("clean/white") IP addresses.
- 🎩 **Industrial TUI**: A complete Terminal User Interface with mouse support, hotkeys, and smooth animations.
- 🛡️ **Graceful Shutdown**: Safe process termination. Press `Ctrl+C` and the program will politely close all threads leaving absolutely no dangling cloud resources.
- 📄 **Log Rotation**: All operations are safely logged to `app_rolling.log` with a capped file size.
- 📱 **Smart Notifications**: Telegram bot support. As soon as the target subnet is acquired, you'll receive a message.
- 🌍 **Multilanguage**: Fully built-in Russian and English environments.

---

### ☁️ Cloud Providers

| Feature | 🟡 Yandex Cloud | 🔵 Reg.ru |
| :--- | :--- | :--- |
| **Rotation Mechanic** | Static Address Rotation in VPC | Full VM (Instance) Re-creation |
| **Authorization** | Service Account Key (JSON) / IAM | API Token |
| **Speed** | ⚡ Very Fast (a few seconds) | 🕒 Moderate (1-2 mins per server) |
| **Best Used For** | Aggressive, continuous, heavy-duty rotation | Discovering specific pools and expanding geo. |

---

### 📖 The Ultimate Setup Guide

#### Step 1: Preparation
Make sure Python >= **3.10** is installed.
Clone the repository:
```bash
git clone https://github.com/censorny/liberal-ip-roller/
cd liberal-ip-roller
pip install -r requirements.txt
```

#### Step 2: Configuring The `config.json`
Open `config.json` in your favorite editor. This file controls the rotation logic.

**For Yandex Cloud:**
* The most reliable way is to create a Service Account in the Yandex Cloud console, give it the `editor` role, generate an "Authorized Key" and save the `.json` file to your PC.
* In `config.json` under `yandex.api.folder_id`, insert your working Cloud Folder ID.
* Set `yandex.api.sa_key_path` to the absolute path of your key (e.g. `/home/user/keys/sa_key.json`). You can leave `iam_token` blank; the app will generate and refresh tokens automatically!

**For Reg.ru:**
* Grab an API Token from the Cloud VPS panel.
* Insert it into `config.json` under `regru.api.api_token`.

**IP Pool Targeting:**
Set up the subnets you are hunting for in `yandex.process.allowed_ranges` and `regru.process.allowed_ranges` formatting using CIDR masks. Example: `"84.201.128.0/18"`.

#### Step 3: Run & Dominate
Launch the application:
```bash
python main.py
# or use the provided run.bat / run.sh
```

1. **Select Provider**: You will be prompted to choose the cloud provider.
2. **Dashboard**: Once inside the main cockpit, press `Start`. The automatic rotation engine will engage.
3. **Monitoring**: Watch real-time API logs, errors, and attempt statistics.
4. **Success**: The engine automatically halts when a target IP is captured. Secure it in your cloud panel.

---

### 💖 Support The Open Source
If this project saved you time, nerves, or money on proxy fees, consider buying the author a coffee. Your support fuels future updates:

| Asset | Network | Wallet Address |
| :--- | :--- | :--- |
| **USDT** | **TON** | `UQAStmfLsz9c3yRA3SeADT5kKdKSUZIt0i6z6B0A6gT884wE` |
| **USDT** | **TRC20** | `THCFoTpjGdaEkGvQe9V8A3WMdQMJ3fUhTq` |
| **USDT** | **SPL (Solana)** | `E1Z978yBMJ3UA4y7xZwv57cBxEUoZ5i9TMsrhcxfVRV6` |
| **USDT** | **ERC20** | `0xc6e0828F6aAF152E82fbEb9f7Abd39051208502F` |
| **USDT** | **BEP20** | `0xc6e0828F6aAF152E82fbEb9f7Abd39051208502F` |

---

## 📈 Project Growth (Star History)
[![Star History Chart](https://api.star-history.com/svg?repos=censorny/liberal-ip-roller&type=Date)](https://star-history.com/#censorny/liberal-ip-roller&Date)

---

## 📄 License & Contact
Released under the **MIT License**. Created with passion by **censorny**.

- **Telegram**: [@censorny](https://t.me/censorny)
- **Discord**: `censorny`

<div align="center">
  <sub>Built with ❤️ for the community.</sub>
</div>
