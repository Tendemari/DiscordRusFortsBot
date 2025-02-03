import os
import asyncio
import datetime
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
MOD_ROLE_IDS = os.getenv('MOD_ROLE_ID', '').strip()
MOD_ROLE_ID = set(map(int, MOD_ROLE_IDS.split(','))) if MOD_ROLE_IDS else set()
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID'))
ALLOWED_CHANNELS = set(map(int, os.getenv('ALLOWED_CHANNELS').split(',')))

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.message_content = True
intents.presences = True

bot = commands.Bot(command_prefix='!', intents=intents)

active_sessions = {}
pending_moderators = set()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def log(message: str):
    timestamp = datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    log_message = f'\033[36m[{timestamp}]\033[0m {message}'
    print(log_message)

def init_folders():
    required_folders = ['voice_logs', 'reports', 'general_reports', 'moderator_info']
    log("Инициализация файловой системы...")
    for folder in required_folders:
        path = os.path.join(BASE_DIR, folder)
        try:
            os.makedirs(path, exist_ok=True)
            log(f"Создана папка: {folder}")
        except Exception as e:
            log(f"\033[31mОшибка при создании папки {folder}: {str(e)}\033[0m")

def save_to_file(user_id: int, content: str, folder_type: str):
    try:
        folder_map = {
            'voice': ('voice_logs', '_voice_logs.txt'),
            'report': ('reports', '_report.txt'),
            'general': ('general_reports', '_general_report.txt')
        }
        folder, suffix = folder_map[folder_type]
        path = os.path.join(BASE_DIR, folder, f"{user_id}{suffix}")
        
        with open(path, 'a', encoding='utf-8') as f:
            f.write(content)
        log(f"\033[32mУспешно сохранено: {user_id} ({folder_type})\033[0m")
    except Exception as e:
        log(f"\033[31mОшибка сохранения: {user_id} ({folder_type}) - {str(e)}\033[0m")

async def validate_session(member: discord.Member, channel: discord.VoiceChannel) -> bool:
    try:
        log(f"Проверка ролей для {member.display_name}: {[role.id for role in member.roles]}")
        log(f"Требуемые роли MOD_ROLE_ID: {MOD_ROLE_ID}")
        log(f"Проверка условий для {member.display_name} в {channel.name}")
        
        if not any(role.id in MOD_ROLE_ID for role in member.roles):
            log(f"Отказ: у пользователя нет ни одной из ролей {MOD_ROLE_ID}")
            return False

        if not isinstance(member, discord.Member):
            log("Ошибка: объект не является участником сервера")
            return False

        if member.bot:
            log("Отказ: пользователь является ботом")
            return False
            
        if not any(role.id in MOD_ROLE_ID for role in member.roles):
            log("Отказ: отсутствует роль модератора")
            return False
            
        if channel.id not in ALLOWED_CHANNELS:
            log(f"Отказ: канал {channel.name} не в разрешенном списке")
            return False
            
        non_mod_users = [
            user for user in channel.members
            if not any(role.id in MOD_ROLE_ID for role in user.roles)
        ]
        
        log(f"Найдено обычных пользователей: {len(non_mod_users)}")
        return len(non_mod_users) >= 1
        
    except Exception as e:
        log(f"Критическая ошибка валидации: {str(e)}")
        return False

async def start_session(member: discord.Member, channel: discord.VoiceChannel):
    try:
        if member.id not in active_sessions:
            active_sessions[member.id] = {
                'guild_id': channel.guild.id,
                'channel': channel.id,
                'start_time': datetime.datetime.now(),
                'participants': [
                    u.id for u in channel.members 
                    if not any(r.id in MOD_ROLE_ID for r in u.roles)
                ]
            }
            log(f"\033[32mСессия начата: {member.display_name} в {channel.name}\033[0m")
            pending_moderators.discard(member.id)
    except Exception as e:
        log(f"\033[31mОшибка старта сессии: {str(e)}\033[0m")

async def stop_session(member: discord.Member, reason: str):
    try:
        if member.id in active_sessions:
            session = active_sessions.pop(member.id)
            duration = datetime.datetime.now() - session['start_time']
            
            log_entry = (
                f"Moderator: {member.id} | "
                f"Channel: {session['channel']} | "
                f"Date: {session['start_time'].strftime('%d.%m.%Y %H:%M:%S')} | "
                f"Duration: {format_duration(duration.total_seconds())}\n"
            )
            
            save_to_file(member.id, log_entry, 'voice')
            log(f"\033[33mСессия остановлена: {member.display_name} - {reason}\033[0m")
            pending_moderators.add(member.id)
    except Exception as e:
        log(f"\033[31mОшибка остановки сессии: {str(e)}\033[0m")

async def stop_session_by_id(user_id: int):
    try:
        if user_id in active_sessions:
            session = active_sessions.pop(user_id)
            duration = datetime.datetime.now() - session['start_time']
            log_entry = f"Moderator: {user_id} | Duration: {format_duration(duration.total_seconds())}\n"
            save_to_file(user_id, log_entry, 'voice')
            pending_moderators.add(user_id)
            log(f"Сессия {user_id} принудительно остановлена")
    except Exception as e:
        log(f"Ошибка при остановке сессии: {str(e)}")

@bot.event
async def on_ready():
    init_folders()
    log(f"\033[32mБот {bot.user.name} успешно запущен!\033[0m")
    log(f"Серверов: {len(bot.guilds)}")
    log(f"Пользователей: {len(bot.users)}")
    log(f"MOD_ROLE_ID: {MOD_ROLE_ID}")
    log(f"ADMIN_ROLE_ID: {ADMIN_ROLE_ID}")
    log(f"ALLOWED_CHANNELS: {ALLOWED_CHANNELS}")
    bot.loop.create_task(background_check())

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    try:
        log(f"Событие голосового статуса: {member.display_name}")
        
        if not before.channel and after.channel:
            if await validate_session(member, after.channel):
                await start_session(member, after.channel)
                
        elif before.channel and not after.channel:
            await stop_session(member, "покинул канал")
            
        elif before.channel and after.channel and before.channel != after.channel:
            await stop_session(member, "перемещение между каналами")
            if await validate_session(member, after.channel):
                await start_session(member, after.channel)
                
    except Exception as e:
        log(f"Фатальная ошибка обработки голосового статуса: {str(e)}")

async def background_check():
    log("Запуск фоновой проверки...")
    while True:
        try:
            await asyncio.sleep(30)
            log(f"Активные сессии: {len(active_sessions)}")
            
            for user_id in list(active_sessions.keys()):
                session = active_sessions[user_id]
                guild = bot.get_guild(session['guild_id'])
                
                if not guild:
                    await stop_session_by_id(user_id)
                    continue
                    
                member = guild.get_member(user_id)
                channel = guild.get_channel(session['channel'])
                
                if not member or not channel or not await validate_session(member, channel):
                    await stop_session(member, "нарушение правил")
            
            log("Попытка возобновления сессий...")
            for guild in bot.guilds:
                for channel in guild.voice_channels:
                    for member in channel.members:
                        if member.id in pending_moderators and await validate_session(member, channel):
                            await start_session(member, channel)
            
        except Exception as e:
            log(f"КРИТИЧЕСКАЯ ОШИБКА В ФОНОВОЙ ПРОВЕРКЕ: {str(e)}")
            await asyncio.sleep(60)

@bot.command(name='reset')
@commands.has_role(ADMIN_ROLE_ID)
async def reset(ctx):
    """Удаляет все данные бота"""
    confirmation_message = await ctx.send("Вы уверены, что хотите сбросить все данные? Это действие нельзя отменить. Введите 'да' для подтверждения.")
    
    def check(m):
        return m.author == ctx.author and m.content.lower() == 'да'
    
    try:
        response = await bot.wait_for('message', check=check, timeout=30.0)
        
        if response.content.lower() == 'да':
            folders = ['voice_logs', 'reports', 'general_reports', 'moderator_info']
            for folder in folders:
                path = os.path.join(BASE_DIR, folder)
                for file in os.listdir(path):
                    os.remove(os.path.join(path, file))
                log(f"Очищена папка: {folder}")
            
            global active_sessions, pending_moderators
            active_sessions.clear()
            pending_moderators.clear()
            
            await ctx.send("✅ Все данные успешно сброшены!")
        else:
            await ctx.send("Сброс данных отменен.")
    except asyncio.TimeoutError:
        await ctx.send("Время ожидания истекло. Сброс данных отменен.")
    except Exception as e:
        await ctx.send(f"❌ Ошибка при сбросе данных: {str(e)}")

@bot.command(name='info')
async def info(ctx):
    """Показывает информацию о боте"""
    embed = discord.Embed(
        title="📊 Бот для учета активности модераторов",
        description="Этот бот помогает отслеживать и анализировать активность модераторов на сервере.",
        color=0x00ff00
    )
    
    # Основные команды
    embed.add_field(
        name="Основные команды:",
        value=(
            "`!send_report [текст]` - отправить доклад (Модераторы)\n"
            "`!generate_report` - сформировать отчет (Главный модератор)\n"
            "`!get_voice_logs @юзер` - показать логи голосовых каналов (Модераторы)\n"
            "`!get_reports @юзер` - показать доклады пользователя (Модераторы)\n"
            "`!reset` - сбросить все данные (Главный модератор)\n"
            "`!info` - показать это сообщение (все)\n"
            "`!set_cf_params @модератор B S D P A F Q` - установить параметры для расчета коэффициента модератора (Главный модератор)\n"
            "`!coefficient` - рассчитать коэффициент модератора (Модераторы)"
        ),
        inline=False
    )

    # Дополнительная информация
    embed.add_field(
        name="Дополнительная информация:",
        value=(
            "Бот автоматически отслеживает активность модераторов в голосовых каналах и сохраняет их действия.\n"
            "Модераторы могут отправлять доклады о своей работе, а главный модератор может генерировать отчеты и сбрасывать данные."
        ),
        inline=False
    )

    # Версия и разработчик
    embed.set_footer(text=f"Версия: 1.0 | Разработчик: {ctx.guild.owner.display_name}")

    await ctx.send(embed=embed)

def calculate_coefficient(B, S, D, P, A, F, Q):
    try:
        # Проверка на "плохого" модератора
        is_bad_moderator = B < 25 if D == 0.8 else B < 40
        
        if is_bad_moderator:
            # Формула для плохих модераторов
            K = 1 / ((1 - B / 200) * (1 - 0.05 * S) * (1 / D) * (1 / P) * (1 / A) * (1 / F) * (1 / Q))
        else:
            # Формула для хороших модераторов
            K = 1 / ((1 + B / 200) * (1 + 0.05 * S) * D * P * A * F * Q)
        
        return K
    except ZeroDivisionError:
        return None

@bot.command(name='set_cf_params')
async def set_cf_params(ctx, member: discord.Member, B: float = None, S: float = None, D: float = None, P: float = None, A: float = None, F: float = None, Q: float = None):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    # Если ни один из параметров не указан, отправляем справочное сообщение
    if all(param is None for param in [B, S, D, P, A, F, Q]):
        embed = discord.Embed(
            title="Инструкция по использованию команды !set_cf_params",
            description="Эта команда устанавливает параметры для расчета коэффициента модератора.",
            color=0x00ff00
        )
        embed.add_field(
            name="Формат команды:",
            value="`!set_cf_params @модератор <B> <S> <D> <P> <A> <F> <Q>`",
            inline=False
        )
        embed.add_field(
            name="Параметры:",
            value=(
                "• **B** - Количество баллов в предыдущем месяце\n"
                "• **S** - Стаж (в месяцах)\n"
                "• **D** - Должность (Хелперы - 1.0; Модераторы - 1.1)\n"
                "• **P** - Повышение должности (если не было - 1, если было то 0.9)\n"
                "• **A** - Активность (5 действий - 1.0; 10 - 1.1; 20 - 1.2)\n"
                "• **F** - Коэффициент штрафа (не было - 1.0; 1 штраф - 1.1; 2 и более - 1.2)\n"
                "• **Q** - Качественный показатель (нет - 1.0; хорошая работа - 0.9; отличная работа - 0.8)"
            ),
            inline=False
        )
        embed.set_footer(text="Пример использования: !set_cf_params @Vilser 100 2 1.0 0.9 1.2 0.9 1.1")
        await ctx.send(embed=embed)
        return

    try:
        params = {
            'B': B,
            'S': S,
            'D': D,
            'P': P,
            'A': A,
            'F': F,
            'Q': Q
        }
        K = calculate_coefficient(**params)
        if K is None:
            await ctx.send("Ошибка расчета коэффициента: деление на ноль.")
            return

        # Сохраняем параметры и коэффициент в файл
        info_path = os.path.join(BASE_DIR, 'moderator_info', f"{member.id}_info.txt")
        with open(info_path, 'w', encoding='utf-8') as f:
            f.write(f"Parameters: {params}\n")
            f.write(f"Coefficient: {K:.4f}\n")

        await ctx.send("Параметры успешно установлены!")
    except Exception as e:
        await ctx.send(f"Ошибка при установке параметров: {str(e)}")

@bot.command(name='coefficient')
async def coefficient(ctx):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    try:
        coefficients = []
        moderator_info_dir = os.path.join(BASE_DIR, 'moderator_info')
        for filename in os.listdir(moderator_info_dir):
            if filename.endswith('_info.txt'):
                user_id = filename.split('_')[0]
                info_path = os.path.join(moderator_info_dir, filename)
                with open(info_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.startswith('Coefficient:'):
                            K = float(line.split(': ')[1])
                            coefficients.append((user_id, K))
                            break

        if not coefficients:
            await ctx.send("Нет данных о коэффициентах модераторов.")
            return

        content = ["Модераторы и их коэффициенты:"]
        for user_id, K in coefficients:
            content.append(f"- Модератор <@{user_id}>: Коэффициент {K:.4f}")

        await ctx.send("\n".join(content))
    except Exception as e:
        await ctx.send(f"Ошибка при расчете коэффициентов: {str(e)}")

@bot.command(name='get_voice_logs')
async def get_voice_logs(ctx, member: discord.Member):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    """Показывает логи голосовых каналов для указанного модератора"""
    try:
        user_id = member.id
        path = os.path.join(BASE_DIR, 'voice_logs', f"{user_id}_voice_logs.txt")
        
        if not os.path.exists(path):
            await ctx.send("🚫 Логов не найдено")
            return
            
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if len(content) > 1900:
            await ctx.send(file=discord.File(path))
        else:
            await ctx.send(f"📅 Логи голосовой активности для {member.mention}:\n```{content}```")
            
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)}")

@bot.command(name='get_reports')
async def get_reports(ctx, member: discord.Member):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    """Показывает все доклады указанного модератора"""
    try:
        user_id = member.id
        path = os.path.join(BASE_DIR, 'reports', f"{user_id}_report.txt")
        
        if not os.path.exists(path):
            await ctx.send("🚫 Докладов не найдено")
            return
            
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if len(content) > 1900:
            await ctx.send(file=discord.File(path))
        else:
            await ctx.send(f"📄 Доклады {member.mention}:\n```{content}```")
            
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)}")

@bot.command(name='send_report')
async def send_report(ctx, *, report_text: str):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    try:
        if len(report_text) < 10:
            await ctx.send("Доклад должен содержать минимум 10 символов")
            return

        report_data = (
            f"Moderator ID: {ctx.author.id}\n"
            f"Date: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
            f"Report:\n{report_text}\n"
            f"----------------------------\n"
        )

        save_to_file(ctx.author.id, report_data, 'report')
        await ctx.send("Доклад успешно сохранён!")
    except Exception as e:
        await ctx.send("Ошибка при сохранении доклада")

@bot.command(name='generate_report')
async def generate_report(ctx):
    if not any(role.id in MOD_ROLE_ID for role in ctx.author.roles):
        await ctx.send("Эта команда доступна только модераторам!")
        return
    try:
        general_reports_dir = os.path.join(BASE_DIR, 'general_reports')
        os.makedirs(general_reports_dir, exist_ok=True)
        all_voice_data = {}
        all_reports = {}
        moderator_info = {}

        # Считываем информацию о коэффициентах модераторов
        moderator_info_dir = os.path.join(BASE_DIR, 'moderator_info')
        for filename in os.listdir(moderator_info_dir):
            if filename.endswith('_info.txt'):
                user_id = filename.split('_')[0]
                info_path = os.path.join(moderator_info_dir, filename)
                with open(info_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    for line in lines:
                        if line.startswith('Coefficient:'):
                            K = float(line.split(': ')[1])
                            moderator_info[user_id] = K
                            break

        # Обработка голосовых логов
        voice_logs_dir = os.path.join(BASE_DIR, 'voice_logs')
        for filename in os.listdir(voice_logs_dir):
            if filename.endswith('_voice_logs.txt'):
                user_id = filename.split('_')[0]
                try:
                    with open(os.path.join(voice_logs_dir, filename), 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        total_seconds = 0
                        start_dates = []
                        end_dates = []
                        for line in lines:
                            parts = line.strip().split(' | ')
                            date_str = parts[2].split(': ')[1]
                            duration_str = parts[3].split(': ')[1]
                            h, m, s = map(int, duration_str.split(':'))
                            total_seconds += h * 3600 + m * 60 + s
                            start_date = datetime.datetime.strptime(date_str, '%d.%m.%Y %H:%M:%S')
                            end_date = start_date + datetime.timedelta(seconds=h*3600 + m*60 + s)
                            start_dates.append(start_date)
                            end_dates.append(end_date)

                        all_voice_data[user_id] = {
                            'total_time': total_seconds,
                            'start_date': min(start_dates) if start_dates else None,
                            'end_date': max(end_dates) if end_dates else None
                        }
                except Exception as e:
                    log(f"Ошибка чтения голосовых логов {filename}: {str(e)}")
                    continue

        # Обработка докладов
        reports_dir = os.path.join(BASE_DIR, 'reports')
        for filename in os.listdir(reports_dir):
            if filename.endswith('_report.txt'):
                user_id = filename.split('_')[0]
                try:
                    with open(os.path.join(reports_dir, filename), 'r', encoding='utf-8') as f:
                        reports = []
                        current_report = {}
                        report_lines = f.readlines()

                        for line in report_lines:
                            line = line.strip()
                            if line.startswith('Moderator ID:'):
                                if current_report:
                                    reports.append(current_report)
                                current_report = {'id': line.split(': ')[1]}
                            elif line.startswith('Date:'):
                                current_report['date'] = line.split(': ')[1]
                            elif line.startswith('Report:'):
                                current_report['text'] = []
                            elif line == '----------------------------':
                                if current_report.get('text') is not None:
                                    current_report['text'] = '\n'.join(current_report['text'])
                                    reports.append(current_report)
                                    current_report = {}
                            elif 'text' in current_report:
                                current_report['text'].append(line.replace('\\n', '\n'))

                        if current_report:
                            reports.append(current_report)
                        all_reports[user_id] = reports
                except Exception as e:
                    log(f"Ошибка при чтении файла {filename}: {str(e)}")
                    continue

        # Генерация индивидуальных отчетов
        for user_id in set(all_voice_data.keys()) | set(all_reports.keys()):
            voice_info = all_voice_data.get(user_id, {'total_time': 0, 'start_date': None, 'end_date': None})
            reports = all_reports.get(user_id, [])
            total_time = voice_info['total_time']
            hours = total_time // 3600
            minutes = (total_time % 3600) // 60
            time_str = f"{hours:02}:{minutes:02}"
            K = moderator_info.get(user_id)
            content = [
                f"Модератор: {user_id}",
                f"Период: {voice_info['start_date'].strftime('%d.%m.%Y') if voice_info['start_date'] else 'N/A'} - {voice_info['end_date'].strftime('%d.%m.%Y') if voice_info['end_date'] else 'N/A'}",
                "────────────────────",
                f"Общее время в голосовых каналах: {time_str}",
                f"Количество докладов: {len(reports)}"
            ]
            if K is not None:
                content.append(f"Коэффициент: {K:.4f}")
            if reports:
                content.append("Список докладов:")
                for report in reports:
                    content.append(f"- {report['date']}: {report['text'].strip()[:50]}{'...' if len(report['text']) > 50 else ''}")
            report_path = os.path.join(general_reports_dir, f"{user_id}_general_report.txt")
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))

        # Генерация общего отчета
        general_content = [
            f"ОБЩИЙ ОТЧЕТ",
            f"Дата генерации: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            "════════════════════════════",
            f"Всего модераторов: {len(set(all_voice_data.keys()) | set(all_reports.keys()))}",
            f"Суммарное время: {sum(data['total_time'] for data in all_voice_data.values()) // 3600} часов",
            f"Всего докладов: {sum(len(reps) for reps in all_reports.values())}",
            "\n════════════════════════════\n"
        ]
        for user_id in set(all_voice_data.keys()) | set(all_reports.keys()):
            voice_info = all_voice_data.get(user_id, {})
            reports = all_reports.get(user_id, [])
            K = moderator_info.get(user_id, None)
            general_content.append(
                f"🔹 Модератор {user_id}:\n"
                f"   - Общее время: {voice_info.get('total_time', 0)//3600} часов\n"
                f"   - Докладов: {len(reports)}\n"
            )
            if K is not None:
                general_content.append(f"   - Коэффициент: {K:.4f}\n")
            if reports:
                general_content.append("   📝 Последние доклады:")
                for report in reports[-100:]:
                    truncated_text = report['text'].strip()[:50] + "..." if len(report['text']) > 1000 else report['text'].strip()
                    general_content.append(f"     ▪ {report['date']}: {truncated_text}")
                general_content.append("")
            general_content.append("────────────────────")
        with open(os.path.join(BASE_DIR, 'general_report.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(general_content))
        
        await ctx.send("Отчеты успешно сгенерированы!")
        log("Генерация отчетов завершена")
    except Exception as e:
        await ctx.send("Ошибка при генерации отчетов")
        log(f"Ошибка генерации отчетов: {str(e)}")

@send_report.error
async def report_error(ctx, error):
    if isinstance(error, commands.MissingRole):
        await ctx.send("Эта команда доступна только модераторам!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Пожалуйста, укажите текст доклада!")
    else:
        await ctx.send("Произошла неизвестная ошибка")

def format_duration(seconds: float) -> str:
    hours, rem = divmod(seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"

if __name__ == '__main__':
    try:
        bot.run(TOKEN)
    except discord.errors.LoginFailure:
        log("Неверный токен бота!")
    except Exception as e:
        log(f"Критическая ошибка: {str(e)}")