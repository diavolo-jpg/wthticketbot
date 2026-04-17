import discord
from discord.ext import commands
from datetime import datetime
import asyncio
from io import StringIO

# ================== НАСТРОЙКИ ==================
# ID каналов и категорий (замените на свои)
TICKET_CATEGORY_ID = 1445372996737826978    # категория для тикетов
LOG_CHANNEL_ID = 1445383918428885154        # канал для логов закрытых тикетов
APPROVAL_CHANNEL_ID = 1445392303874117744   # канал для подтверждения смены ника

# ================== ИНИЦИАЛИЗАЦИЯ БОТА ==================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Хранилища данных
active_tickets = {}          # {channel_id: author_id}
nickname_requests = {}       # {message_id: request_data}

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==================
async def save_ticket_log(channel: discord.TextChannel):
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
                    file=discord.File(log_file, filename=f"ticket_{channel.name}.txt")
                )
            else:
                embed = discord.Embed(
                    title=f"📁 Лог тикета #{channel.name}",
                    description=f"```{log_text[:1800]}...```" if len(log_text) > 1800 else f"```{log_text}```",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                await log_channel.send(embed=embed)
    except Exception as e:
        print(f"Ошибка при сохранении лога: {e}")

# ================== МОДАЛЬНЫЕ ОКНА ==================
class NicknameModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Смена никнейма")
        
        self.add_item(discord.ui.TextInput(
            label="Новый никнейм",
            placeholder="Введите желаемый никнейм (2-32 символа)",
            custom_id="nickname_input",
            min_length=2,
            max_length=32
        ))
        self.add_item(discord.ui.TextInput(
            label="Причина смены",
            placeholder="Укажите причину смены ника (необязательно)",
            custom_id="reason_input",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=200
        ))

    async def callback(self, interaction: discord.Interaction):
        new_nick = self.children[0].value
        reason = self.children[1].value or "Не указана"

        request_data = {
            "user_id": interaction.user.id,
            "user_name": str(interaction.user),
            "old_nick": interaction.user.display_name,
            "new_nick": new_nick,
            "reason": reason,
            "timestamp": datetime.now(),
            "status": "pending"
        }

        approval_channel = bot.get_channel(APPROVAL_CHANNEL_ID)
        if not approval_channel:
            await interaction.response.send_message("❌ Ошибка: канал для подтверждения не найден!", ephemeral=True)
            return

        embed = discord.Embed(
            title="📝 Заявка на смену никнейма",
            color=discord.Color.orange(),
            timestamp=datetime.now()
        )
        embed.add_field(name="👤 Пользователь", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        embed.add_field(name="📛 Текущий ник", value=interaction.user.display_name, inline=True)
        embed.add_field(name="🆕 Запрошенный ник", value=new_nick, inline=True)
        embed.add_field(name="📋 Причина", value=reason, inline=False)
        embed.set_footer(text=f"ID: {interaction.user.id}")

        view = discord.ui.View(timeout=None)
        approve_button = discord.ui.Button(label="✅ Одобрить", style=discord.ButtonStyle.success,
                                           custom_id=f"approve_nick_{interaction.user.id}")
        deny_button = discord.ui.Button(label="❌ Отклонить", style=discord.ButtonStyle.danger,
                                        custom_id=f"deny_nick_{interaction.user.id}")
        view.add_item(approve_button)
        view.add_item(deny_button)

        message = await approval_channel.send(embed=embed, view=view)
        nickname_requests[message.id] = request_data

        await interaction.response.send_message(
            f"✅ Ваша заявка на смену ника отправлена на рассмотрение!\n"
            f"**Запрошенный ник:** `{new_nick}`\n"
            f"Администраторы рассмотрят её в ближайшее время.",
            ephemeral=True
        )

# ================== ПРЕДСТАВЛЕНИЯ (VIEWS) ==================
class NicknameRequestView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔄 Подать заявку на смену ника", style=discord.ButtonStyle.primary,
                       custom_id="request_nickname_change")
    async def request_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(NicknameModal())

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Отчет об ошибке", value="Отчет об ошибке"),
            discord.SelectOption(label="Жалоба на игрока/администратора", value="Жалоба на игрока/администратора"),
            discord.SelectOption(label="Общая поддержка", value="Общая поддержка"),
            discord.SelectOption(label="Вопрос по оплате", value="Вопрос по оплате"),
            discord.SelectOption(label="Другое", value="Другое")
        ]
        super().__init__(placeholder="Выберите категорию", options=options, custom_id="ticket_select")

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        guild = interaction.guild
        author = interaction.user

        ticket_category = guild.get_channel(TICKET_CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            author: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            guild.me: discord.PermissionOverwrite(
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

        embed = discord.Embed(
            title="🎫 Тикет открыт",
            description=f"Спасибо за обращение, {author.mention}!",
            color=discord.Color.green()
        )
        embed.add_field(name="Категория", value=selected_value, inline=True)
        embed.add_field(name="Создан", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.add_field(name="Статус", value="🟢 Открыт", inline=True)
        embed.set_footer(text="Поддержка ответит вам в ближайшее время")

        view = discord.ui.View(timeout=None)
        close_button = discord.ui.Button(label="Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="close_ticket_button")
        view.add_item(close_button)

        await ticket_channel.send(content=f"{author.mention}", embed=embed, view=view)
        await interaction.response.send_message(f"✅ Тикет создан: {ticket_channel.mention}", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# ================== СОБЫТИЯ ==================
@bot.event
async def on_ready():
    print(f'✅ Бот {bot.user} запущен!')
    await bot.tree.sync()
    print(f"✅ Команды синхронизированы.")

@bot.event
async def on_interaction(interaction: discord.Interaction):
    # Обработка кнопок и модальных окон
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id", "")
        
        # ---- Кнопки тикетов ----
        if custom_id == "close_ticket_button":
            author_id = active_tickets.get(interaction.channel.id)
            if not author_id:
                await interaction.response.send_message("❌ Не удалось определить автора тикета.", ephemeral=True)
                return

            if interaction.user.id != author_id and not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("❌ Вы не можете закрыть этот тикет!", ephemeral=True)
                return

            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Да, закрыть", style=discord.ButtonStyle.danger, custom_id="confirm_close"))
            view.add_item(discord.ui.Button(label="Отмена", style=discord.ButtonStyle.secondary, custom_id="cancel_close"))
            await interaction.response.send_message("⚠️ Вы уверены, что хотите закрыть тикет?", view=view, ephemeral=True)

        elif custom_id == "confirm_close":
            await save_ticket_log(interaction.channel)
            await interaction.channel.delete(reason=f"Тикет закрыт пользователем {interaction.user}")
            await interaction.response.send_message("✅ Тикет закрыт.", ephemeral=True)

        elif custom_id == "cancel_close":
            await interaction.response.send_message("❌ Закрытие тикета отменено.", ephemeral=True)

        # ---- Кнопки заявок на смену ника ----
        elif custom_id.startswith("approve_nick_"):
            user_id = int(custom_id.split("_")[2])
            request_data = nickname_requests.get(interaction.message.id)

            if not request_data:
                await interaction.response.send_message("❌ Заявка не найдена!", ephemeral=True)
                return

            if not interaction.user.guild_permissions.manage_nicknames:
                await interaction.response.send_message("❌ У вас нет прав для подтверждения заявок!", ephemeral=True)
                return

            try:
                member = interaction.guild.get_member(user_id)
                if not member:
                    await interaction.response.send_message("❌ Пользователь не найден на сервере!", ephemeral=True)
                    return

                old_nick = member.display_name
                await member.edit(nick=request_data["new_nick"])

                embed = interaction.message.embeds[0]
                embed.color = discord.Color.green()
                embed.add_field(name="✅ Статус", value=f"Одобрено администратором {interaction.user.mention}", inline=False)
                embed.add_field(name="⏰ Время обработки", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=False)

                await interaction.message.edit(embed=embed, view=None)

                try:
                    await member.send(
                        f"🎉 Ваша заявка на смену ника **одобрена**!\n"
                        f"**Старый ник:** {old_nick}\n"
                        f"**Новый ник:** {request_data['new_nick']}\n"
                        f"**Администратор:** {interaction.user.display_name}"
                    )
                except:
                    pass

                await interaction.response.send_message(f"✅ Ник пользователя {member.mention} успешно изменен!", ephemeral=True)
                nickname_requests.pop(interaction.message.id, None)

            except discord.Forbidden:
                await interaction.response.send_message("❌ У бота недостаточно прав для изменения ника!", ephemeral=True)
            except discord.HTTPException as e:
                await interaction.response.send_message(f"❌ Ошибка при изменении ника: {e}", ephemeral=True)

        elif custom_id.startswith("deny_nick_"):
            user_id = int(custom_id.split("_")[2])
            request_data = nickname_requests.get(interaction.message.id)

            if not request_data:
                await interaction.response.send_message("❌ Заявка не найдена!", ephemeral=True)
                return

            if not interaction.user.guild_permissions.manage_nicknames:
                await interaction.response.send_message("❌ У вас нет прав для отклонения заявок!", ephemeral=True)
                return

            modal = NicknameDenyModal(interaction.message.id)
            await interaction.response.send_modal(modal)

    elif interaction.type == discord.InteractionType.modal_submit:
        custom_id = interaction.data.get("custom_id", "")
        if custom_id.startswith("deny_reason_"):
            message_id = int(custom_id.split("_")[2])
            request_data = nickname_requests.get(message_id)

            if not request_data:
                await interaction.response.send_message("❌ Заявка не найдена!", ephemeral=True)
                return

            reason = interaction.data["components"][0]["components"][0]["value"]

            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.add_field(name="❌ Статус", value=f"Отклонено администратором {interaction.user.mention}", inline=False)
            embed.add_field(name="📝 Причина отказа", value=reason, inline=False)
            embed.add_field(name="⏰ Время обработки", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=False)

            await interaction.message.edit(embed=embed, view=None)

            try:
                member = interaction.guild.get_member(request_data["user_id"])
                if member:
                    await member.send(
                        f"😔 Ваша заявка на смену ника **отклонена**.\n"
                        f"**Запрошенный ник:** {request_data['new_nick']}\n"
                        f"**Причина отказа:** {reason}\n"
                        f"**Администратор:** {interaction.user.display_name}"
                    )
            except:
                pass

            await interaction.response.send_message("✅ Заявка отклонена, пользователь уведомлен!", ephemeral=True)
            nickname_requests.pop(message_id, None)

class NicknameDenyModal(discord.ui.Modal):
    def __init__(self, message_id: int):
        super().__init__(title="Причина отказа", custom_id=f"deny_reason_{message_id}")
        self.add_item(discord.ui.TextInput(
            label="Причина отказа",
            placeholder="Укажите причину отказа пользователю",
            style=discord.TextStyle.paragraph,
            max_length=500
        ))

    async def callback(self, interaction: discord.Interaction):
        # Этот метод не будет вызван, так как мы обрабатываем модальные окна в on_interaction
        pass

# ================== СЛЭШ-КОМАНДЫ ==================
@bot.tree.command(name="ticket", description="Создать тикет")
async def ticket(interaction: discord.Interaction):
    view = TicketView()
    await interaction.response.send_message("🎫 Пожалуйста, выберите категорию для вашего тикета:", view=view)

@bot.tree.command(name="force_close", description="Принудительно закрыть текущий тикет (администрация)")
@commands.has_permissions(manage_channels=True)
async def force_close(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel) or not interaction.channel.name.startswith("ticket-"):
        await interaction.response.send_message("❌ Эта команда работает только в каналах тикетов!", ephemeral=True)
        return

    await save_ticket_log(interaction.channel)
    await interaction.response.send_message("✅ Тикет закрыт.")
    await asyncio.sleep(1)
    await interaction.channel.delete(reason=f"Тикет закрыт администратором {interaction.user}")

@bot.tree.command(name="setup_nickname_panel", description="Создать панель для подачи заявок на смену ника (только для администрации)")
@commands.has_permissions(administrator=True)
async def setup_nickname_panel(interaction: discord.Interaction):
    embed = discord.Embed(
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
        color=discord.Color.blue()
    )
    view = NicknameRequestView()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="view_nickname_requests", description="Показать все активные заявки на смену ника (администрация)")
@commands.has_permissions(manage_nicknames=True)
async def view_nickname_requests(interaction: discord.Interaction):
    if not nickname_requests:
        await interaction.response.send_message("📭 Активных заявок на смену ника нет.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Активные заявки на смену ника",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )

    for msg_id, request in nickname_requests.items():
        user = interaction.guild.get_member(request["user_id"])
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

    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== ЗАПУСК БОТА ==================
if __name__ == "__main__":
    bot.run("MTQ5NDcwNTM3NTA5NjczMzg0Nw.GmtqJy.fItaXjNZKD6qajQ10ACpC3c1aYeR312s4pOfKM")  # Замените на реальный токен
