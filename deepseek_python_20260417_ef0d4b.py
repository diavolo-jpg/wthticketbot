import disnake
from disnake.ext import commands
from datetime import datetime
import asyncio
from io import StringIO

# ================== НАСТРОЙКИ ==================
# ID каналов и категорий (замените на свои)
TICKET_CATEGORY_ID = 1445372996737826978    # категория для тикетов
LOG_CHANNEL_ID = 1445383918428885154        # канал для логов закрытых тикетов
APPROVAL_CHANNEL_ID = 1445392303874117744   # канал для подтверждения смены ника

# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================
intents = disnake.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Хранилища данных
active_tickets = {}          # {channel_id: author_id}
nickname_requests = {}       # {message_id: request_data}

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
async def save_ticket_log(channel: disnake.TextChannel):
    """Сохраняет историю переписки тикета в лог-канал"""
    try:
        log_channel = channel.guild.get_channel(LOG_CHANNEL_ID)
        if not log_channel:
            return

        messages = []
        async for message in channel.history(limit=200, oldest_first=True):
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            messages.append(f"[{timestamp}] {message.author.display_name}: {message.content}")

        if messages:
            log_text = f"📋 Лог тикета #{channel.name}\n" + "\n".join(messages)

            if len(log_text) > 1900:
                log_file = StringIO(log_text)
                await log_channel.send(
                    f"📁 Лог тикета `{channel.name}` (закрыт {datetime.now().strftime('%d.%m.%Y %H:%M')})",
                    file=disnake.File(log_file, filename=f"ticket_{channel.name}.txt")
                )
            else:
                embed = disnake.Embed(
                    title=f"📁 Лог тикета #{channel.name}",
                    description=f"```{log_text[:1800]}...```" if len(log_text) > 1800 else f"```{log_text}```",
                    color=disnake.Color.blue(),
                    timestamp=datetime.now()
                )
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Ошибка при сохранении лога: {e}")

# ================== МОДАЛЬНЫЕ ОКНА ==================
class NicknameModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Новый никнейм",
                placeholder="Введите желаемый никнейм (2-32 символа)",
                custom_id="nickname_input",
                min_length=2,
                max_length=32
            ),
            disnake.ui.TextInput(
                label="Причина смены",
                placeholder="Укажите причину смены ника (необязательно)",
                custom_id="reason_input",
                style=disnake.TextInputStyle.paragraph,
                required=False,
                max_length=200
            )
        ]
        super().__init__(title="Смена никнейма", components=components, custom_id="nickname_modal")

    async def callback(self, inter: disnake.ModalInteraction):
        new_nick = inter.text_values["nickname_input"]
        reason = inter.text_values["reason_input"] or "Не указана"

        request_data = {
            "user_id": inter.user.id,
            "user_name": str(inter.user),
            "old_nick": inter.user.display_name,
            "new_nick": new_nick,
            "reason": reason,
            "timestamp": datetime.now(),
            "status": "pending"
        }

        approval_channel = bot.get_channel(APPROVAL_CHANNEL_ID)
        if not approval_channel:
            await inter.response.send_message("❌ Ошибка: канал для подтверждения не найден!", ephemeral=True)
            return

        embed = disnake.Embed(
            title="📝 Заявка на смену никнейма",
            color=disnake.Color.orange(),
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 Пользователь", value=f"{inter.user.mention}\n`{inter.user}`", inline=False)
        embed.add_field(name="📛 Текущий ник", value=inter.user.display_name, inline=True)
        embed.add_field(name="🆕 Запрошенный ник", value=new_nick, inline=True)
        embed.add_field(name="📋 Причина", value=reason, inline=False)
        embed.set_footer(text=f"ID: {inter.user.id}")

        view = disnake.ui.View(timeout=None)
        approve_button = disnake.ui.Button(label="✅ Одобрить", style=disnake.ButtonStyle.success,
                                           custom_id=f"approve_nick_{inter.user.id}")
        deny_button = disnake.ui.Button(label="❌ Отклонить", style=disnake.ButtonStyle.danger,
                                        custom_id=f"deny_nick_{inter.user.id}")
        view.add_item(approve_button)
        view.add_item(deny_button)

        message = await approval_channel.send(embed=embed, view=view)
        nickname_requests[message.id] = request_data

        await inter.response.send_message(
            f"✅ Ваша заявка на смену ника отправлена на рассмотрение!\n"
            f"**Запрошенный ник:** `{new_nick}`\n"
            f"Администраторы рассмотрят её в ближайшее время.",
            ephemeral=True
        )

# ================== ПРЕДСТАВЛЕНИЯ (VIEWS) ==================
class NicknameRequestView(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="🔄 Подать заявку на смену ника", style=disnake.ButtonStyle.primary,
                       custom_id="request_nickname_change")
    async def request_button(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        await interaction.response.send_modal(NicknameModal())

# ================== СОБЫТИЯ ==================
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    try:
        synced = await bot.sync_commands()
        print(f"✅ Синхронизировано {len(synced)} команд.")
    except Exception as e:
        print(f"❌ Ошибка синхронизации команд: {e}")

@bot.event
async def on_dropdown(inter: disnake.MessageInteraction):
    if inter.component.custom_id != "ticket_select":
        return

    selected_value = inter.values[0]
    guild = inter.guild
    author = inter.author

    ticket_category = guild.get_channel(TICKET_CATEGORY_ID)

    overwrites = {
        guild.default_role: disnake.PermissionOverwrite(read_messages=False),
        author: disnake.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me: disnake.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True
        )
    }

    ticket_channel = await guild.create_text_channel(
        name=f"ticket-{datetime.now().strftime('%d%m')}",
        overwrites=overwrites,
        category=ticket_category,
        topic=f"Тикет от {author.name} | Категория: {selected_value} | ID: {author.id}"
    )

    active_tickets[ticket_channel.id] = author.id

    embed = disnake.Embed(
        title="🎫 Тикет открыт",
        description=f"Спасибо за обращение, {author.mention}!",
        color=disnake.Color.green()
    )
    embed.add_field(name="Категория", value=selected_value, inline=True)
    embed.add_field(name="Создан", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
    embed.add_field(name="Статус", value="🟢 Открыт", inline=True)
    embed.set_footer(text="Поддержка ответит вам в ближайшее время")

    # Кнопка закрытия (будет обработана в on_button_click)
    view = disnake.ui.View(timeout=None)
    close_button = disnake.ui.Button(label="Закрыть тикет", style=disnake.ButtonStyle.danger, custom_id="close_ticket_button")
    view.add_item(close_button)

    await ticket_channel.send(content=f"{author.mention}", embed=embed, view=view)
    await inter.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

@bot.event
async def on_button_click(inter: disnake.MessageInteraction):
    custom_id = inter.component.custom_id

    # ---- Кнопки тикетов ----
    if custom_id == "close_ticket_button":
        author_id = active_tickets.get(inter.channel.id)
        if not author_id:
            await inter.response.send_message("❌ Не удалось определить автора тикета.", ephemeral=True)
            return

        if inter.user.id != author_id and not inter.user.guild_permissions.manage_channels:
            await inter.response.send_message("❌ Вы не можете закрыть этот тикет!", ephemeral=True)
            return

        confirm_view = disnake.ui.View()
        confirm_view.add_item(disnake.ui.Button(label="Да, закрыть", style=disnake.ButtonStyle.danger, custom_id="confirm_close"))
        confirm_view.add_item(disnake.ui.Button(label="Отмена", style=disnake.ButtonStyle.secondary, custom_id="cancel_close"))
        await inter.response.send_message("⚠️ Вы уверены, что хотите закрыть тикет?", view=confirm_view, ephemeral=True)

    elif custom_id == "confirm_close":
        await save_ticket_log(inter.channel)
        await inter.channel.delete(reason=f"Тикет закрыт пользователем {inter.user}")

    elif custom_id == "cancel_close":
        await inter.response.send_message("❌ Закрытие тикета отменено.", ephemeral=True)

    # ---- Кнопки заявок на смену ника ----
    elif custom_id.startswith("approve_nick_"):
        user_id = int(custom_id.split("_")[2])
        request_data = nickname_requests.get(inter.message.id)

        if not request_data:
            await inter.response.send_message("❌ Заявка не найдена!", ephemeral=True)
            return

        if not inter.user.guild_permissions.manage_nicknames:
            await inter.response.send_message("❌ У вас нет прав для подтверждения заявок!", ephemeral=True)
            return

        try:
            member = inter.guild.get_member(user_id)
            if not member:
                await inter.response.send_message("❌ Пользователь не найден на сервере!", ephemeral=True)
                return

            old_nick = member.display_name
            await member.edit(nick=request_data["new_nick"])

            embed = inter.message.embeds[0]
            embed.color = disnake.Color.green()
            embed.add_field(name="✅ Статус", value=f"Одобрено администратором {inter.user.mention}", inline=False)
            embed.add_field(name="⏰ Время обработки", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=False)

            await inter.message.edit(embed=embed, view=None)

            try:
                await member.send(
                    f"🎉 Ваша заявка на смену ника **одобрена**!\n"
                    f"**Старый ник:** {old_nick}\n"
                    f"**Новый ник:** {request_data['new_nick']}\n"
                    f"**Администратор:** {inter.user.display_name}"
                )
            except:
                pass

            await inter.response.send_message(f"✅ Ник пользователя {member.mention} успешно изменен!", ephemeral=True)
            nickname_requests.pop(inter.message.id, None)

        except disnake.Forbidden:
            await inter.response.send_message("❌ У бота недостаточно прав для изменения ника!", ephemeral=True)
        except disnake.HTTPException as e:
            await inter.response.send_message(f"❌ Ошибка при изменении ника: {e}", ephemeral=True)

    elif custom_id.startswith("deny_nick_"):
        user_id = int(custom_id.split("_")[2])
        request_data = nickname_requests.get(inter.message.id)

        if not request_data:
            await inter.response.send_message("❌ Заявка не найдена!", ephemeral=True)
            return

        if not inter.user.guild_permissions.manage_nicknames:
            await inter.response.send_message("❌ У вас нет прав для отклонения заявок!", ephemeral=True)
            return

        modal = disnake.ui.Modal(
            title="Причина отказа",
            custom_id=f"deny_reason_{inter.message.id}",
            components=[
                disnake.ui.TextInput(
                    label="Причина отказа",
                    placeholder="Укажите причину отказа пользователю",
                    custom_id="deny_reason",
                    style=disnake.TextInputStyle.paragraph,
                    max_length=500
                )
            ]
        )
        await inter.response.send_modal(modal)

@bot.event
async def on_modal_submit(inter: disnake.ModalInteraction):
    if inter.custom_id.startswith("deny_reason_"):
        message_id = int(inter.custom_id.split("_")[2])
        request_data = nickname_requests.get(message_id)

        if not request_data:
            await inter.response.send_message("❌ Заявка не найдена!", ephemeral=True)
            return

        reason = inter.text_values["deny_reason"]

        embed = inter.message.embeds[0]
        embed.color = disnake.Color.red()
        embed.add_field(name="❌ Статус", value=f"Отклонено администратором {inter.user.mention}", inline=False)
        embed.add_field(name="📝 Причина отказа", value=reason, inline=False)
        embed.add_field(name="⏰ Время обработки", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=False)

        await inter.message.edit(embed=embed, view=None)

        try:
            member = inter.guild.get_member(request_data["user_id"])
            if member:
                await member.send(
                    f"😔 Ваша заявка на смену ника **отклонена**.\n"
                    f"**Запрошенный ник:** {request_data['new_nick']}\n"
                    f"**Причина отказа:** {reason}\n"
                    f"**Администратор:** {inter.user.display_name}"
                )
        except:
            pass

        await inter.response.send_message("✅ Заявка отклонена, пользователь уведомлен!", ephemeral=True)
        nickname_requests.pop(message_id, None)

# ================== СЛЭШ-КОМАНДЫ ==================
@bot.slash_command(description="Создать тикет")
async def ticket(inter: disnake.ApplicationCommandInteraction):
    select_menu = disnake.ui.Select(
        custom_id="ticket_select",
        placeholder="Выберите категорию",
        options=[
            disnake.SelectOption(label="Отчет об ошибке", value="Отчет об ошибке"),
            disnake.SelectOption(label="Жалоба на игрока/администратора", value="Жалоба на игрока/администратора"),
            disnake.SelectOption(label="Общая поддержка", value="Общая поддержка"),
            disnake.SelectOption(label="Вопрос по оплате", value="Вопрос по оплате"),
            disnake.SelectOption(label="Другое", value="Другое")
        ]
    )
    view = disnake.ui.View()
    view.add_item(select_menu)
    await inter.response.send_message("🎫 Пожалуйста, выберите категорию для вашего тикета:", view=view)

@bot.slash_command(description="Принудительно закрыть текущий тикет (администрация)")
@commands.has_permissions(manage_channels=True)
async def force_close(inter: disnake.ApplicationCommandInteraction):
    if not isinstance(inter.channel, disnake.TextChannel) or not inter.channel.name.startswith("ticket-"):
        await inter.response.send_message("❌ Эта команда работает только в каналах тикетов!", ephemeral=True)
        return

    await save_ticket_log(inter.channel)
    await inter.response.send_message("✅ Тикет закрыт.")
    await asyncio.sleep(1)
    await inter.channel.delete(reason=f"Тикет закрыт администратором {inter.user}")

@bot.slash_command(description="Создать панель для подачи заявок на смену ника (только для администрации)")
@commands.has_permissions(administrator=True)
async def setup_nickname_panel(inter: disnake.ApplicationCommandInteraction):
    embed = disnake.Embed(
        title="🔄 Смена никнейма на сервере",
        description=(
            "Хотите изменить свой никнейм на этом сервере?\n\n"
            "**Как это работает:**\n"
            "1. Нажмите кнопку ниже\n"
            "2. Введите желаемый никнейм\n"
            "3. Укажите причину смены (необязательно)\n"
            "4. Ожидайте рассмотрения заявки администрацией\n\n"
            "⚠️ **Правила:**\n"
            "• Ник должен соответствовать правилам сервера\n"
            "• Запрещены оскорбительные и провокационные ники\n"
            "• Администрация оставляет право отказать без объяснения причин"
        ),
        color=disnake.Color.blue()
    )
    view = NicknameRequestView()
    await inter.response.send_message(embed=embed, view=view)

@bot.slash_command(description="Показать все активные заявки на смену ника (администрация)")
@commands.has_permissions(manage_nicknames=True)
async def view_nickname_requests(inter: disnake.ApplicationCommandInteraction):
    if not nickname_requests:
        await inter.response.send_message("📭 Активных заявок на смену ника нет.", ephemeral=True)
        return

    embed = disnake.Embed(
        title="📋 Активные заявки на смену ника",
        color=disnake.Color.blue(),
        timestamp=datetime.now()
    )

    for msg_id, request in nickname_requests.items():
        user = inter.guild.get_member(request["user_id"])
        user_mention = user.mention if user else f"Пользователь не найден (ID: {request['user_id']})"

        embed.add_field(
            name=f"Заявка #{msg_id}",
            value=(
                f"👤 {user_mention}\n"
                f"📛 С: `{request['old_nick']}` → На: `{request['new_nick']}`\n"
                f"📋 Причина: {request['reason']}\n"
                f"⏰ Подана: <t:{int(request['timestamp'].timestamp())}:R>"
            ),
            inline=False
        )

    await inter.response.send_message(embed=embed, ephemeral=True)

# ================== ЗАПУСК БОТА ==================
if __name__ == "__main__":
    bot.run("ВАШ_ТОКЕН_БОТА")  # Замените на реальный токен