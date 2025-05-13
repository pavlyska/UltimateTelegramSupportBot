from config import *
from base import *

bot = telebot.TeleBot(BOT_TOKEN)

#######
# Клавиатуры
#######
user_main_menu = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
user_main_menu.row("📝 Создать тикет")
user_main_menu.row("📜 История тикетов")

user_blocked_menu = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
user_blocked_menu.row("⚖️ Подать обжалование")
user_blocked_menu.row("ℹ️ Узнать причину блокировки")

admin_menu = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
admin_menu.row("➕ Добавить агента", "➖ Удалить агента")
admin_menu.row("📋 Список тикетов")
admin_menu.row("👥 Список персонала")
admin_menu.row("📊 Статистика")
admin_menu.row("⚖️ Обжалования")

agent_menu = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
agent_menu.row("📋 Список тикетов")
agent_menu.row("👥 Список персонала")
agent_menu.row("📊 Статистика")
agent_menu.row("⚖️ Обжалования")


#######
# Кнопка "⚖️ Обжалования"
#######
@bot.message_handler(func=lambda message: message.text == "⚖️ Обжалования")
def show_appeals_list(message):
    """
    Обработчик кнопки "⚖️ Обжалования"
    Показывает список всех обжалований с возможностью одобрить или отклонить
    Доступно только для персонала (агентов и администраторов)
    """
    staff_id = message.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (staff_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(staff_id, 
                         "⚠️ У вас нет доступа к списку обжалований.")
        return
    
    try:
        # Получаем список обжалований с username из таблицы users
        cursor.execute("""
            SELECT a.appeal_id, a.user_id, a.reason, a.status, a.related_ticket_id, a.created_at, u.username
            FROM appeals a
            LEFT JOIN users u ON a.user_id = u.user_id
            ORDER BY a.created_at DESC
        """)
        appeals = cursor.fetchall()
        
        if not appeals:
            bot.send_message(
                staff_id,
                "📋 Список обжалований пуст.",
                reply_markup=admin_menu if staff[0] == "admin" else agent_menu
            )
            return
        
        # Формируем ответ для каждого обжалования
        for appeal in appeals:
            appeal_id, user_id, reason, status, ticket_id, created_at, username = appeal
            username = f"@{username}" if username else "Нет тега"
            
            response = (
                f"📌 Обжалование #{appeal_id}\n"
                f"👤 Пользователь: {username} ({user_id})\n"
                f"🔗 Тикет: #{ticket_id}\n"
                f"📝 Причина: {reason}\n"
                f"📊 Статус: {status}\n"
                f"🕒 Создано: {created_at}\n"
            )
            
            # Добавляем инлайн-кнопки только для обжалований со статусом pending
            if status == "pending":
                keyboard = InlineKeyboardMarkup()
                keyboard.row(
                    InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_appeal_{appeal_id}_{user_id}"),
                    InlineKeyboardButton("❌ Отказать", callback_data=f"reject_appeal_{appeal_id}_{user_id}")
                )
                bot.send_message(staff_id, response, reply_markup=keyboard)
            else:
                bot.send_message(staff_id, response)
    
    except sqlite3.Error as e:
        bot.send_message(staff_id, 
                         "❌ Ошибка при получении списка обжалований. Попробуйте позже.")
        print(f"Database error in show_appeals_list: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_appeal_"))
def reject_appeal(call):
    """
    Обработчик отказа в обжаловании
    """
    data = call.data.split("_")
    appeal_id = int(data[2])
    user_id = int(data[3])

    try:
        # Проверяем права доступа пользователя
        cursor.execute("""
            SELECT role FROM staff 
            WHERE user_id = ? AND (role = 'admin' OR role = 'agent')
        """, (call.from_user.id,))
        staff = cursor.fetchone()
        if not staff:
            bot.answer_callback_query(call.id, "❌ У вас нет доступа к этим действиям.", show_alert=True)
            return
        
        # Запрашиваем причину отказа
        bot.send_message(
            call.message.chat.id,
            "📝 Укажите причину отказа в обжаловании:"
        )
        bot.register_next_step_handler(call.message, lambda m: process_reject_appeal(m, appeal_id, user_id, call))
    
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке запроса.", show_alert=True)
        print(f"Error in reject_appeal handler: {e}")

def process_reject_appeal(message, appeal_id, user_id, call):
    """
    Обработка причины отказа в обжаловании
    """
    try:
        reason = message.text.strip()
        
        # Начинаем транзакцию
        conn.execute("BEGIN")
        
        # Обновляем статус обжалования
        cursor.execute("""
            UPDATE appeals 
            SET status = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE appeal_id = ?
        """, (f"rejected: {reason}", appeal_id))
        
        # Фиксируем изменения
        conn.commit()
        
        # Уведомляем пользователя о отказе
        try:
            bot.send_message(
                user_id,
                f"❌ Ваше обжалование отклонено. Причина: {reason}",
                reply_markup=user_blocked_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        
        # Обновляем сообщение персонала
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n❌ Обжалование отклонено. Причина: {reason}",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, "✅ Обжалование успешно отклонено.")
    
    except sqlite3.Error as e:
        conn.rollback()  # Откатываем изменения при ошибке базы данных
        error_message = f"Database error during appeal rejection: {e}"
        print(error_message)
        bot.answer_callback_query(call.id, "❌ Ошибка базы данных. Попробуйте позже.", show_alert=True)
        bot.send_message(call.from_user.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова позже.")
    
    except Exception as e:
        conn.rollback()  # Откатываем изменения при любых других ошибках
        error_message = f"Unexpected error during appeal rejection: {e}"
        print(error_message)
        bot.answer_callback_query(call.id, "❌ Неизвестная ошибка.", show_alert=True)
        bot.send_message(call.from_user.id, "⚠️ Произошла неизвестная ошибка. Пожалуйста, обратитесь к разработчику.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_appeal_"))
def approve_appeal(call):
    """
    Обработчик одобрения обжалования
    """
    data = call.data.split("_")
    appeal_id = int(data[2])
    user_id = int(data[3])

    try:
        # Начинаем транзакцию
        conn.execute("BEGIN")
        
        # Проверяем права пользователя
        cursor.execute("""
            SELECT role FROM staff 
            WHERE user_id = ? AND (role = 'admin' OR role = 'agent')
        """, (call.from_user.id,))
        staff = cursor.fetchone()
        if not staff:
            bot.answer_callback_query(call.id, "❌ У вас нет доступа к этим действиям.", show_alert=True)
            conn.rollback()  # Откатываем транзакцию при ошибке прав доступа
            return
        
        # Обновляем статус обжалования
        cursor.execute("""
            UPDATE appeals 
            SET status = 'approved', updated_at = CURRENT_TIMESTAMP 
            WHERE appeal_id = ?
        """, (appeal_id,))
        
        # Разблокируем пользователя
        cursor.execute("""
            UPDATE users 
            SET is_blocked = 0, block_reason = NULL, last_appeal_date = NULL 
            WHERE user_id = ?
        """, (user_id,))
        
        # Фиксируем изменения
        conn.commit()
        
        # Уведомляем пользователя о разблокировке
        try:
            bot.send_message(
                user_id,
                "✅ Ваше обжалование одобрено! Вы разблокированы.",
                reply_markup=user_main_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        
        # Обновляем сообщение персонала
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n✅ Обжалование одобрено администратором.",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, "✅ Обжалование успешно одобрено.")
    
    except sqlite3.Error as e:
        conn.rollback()  # Откатываем изменения при ошибке базы данных
        error_message = f"Database error during appeal approval: {e}"
        print(error_message)
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке обжалования.", show_alert=True)
        bot.send_message(call.from_user.id, "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова позже.")
    
    except Exception as e:
        conn.rollback()  # Откатываем изменения при любых других ошибках
        error_message = f"Unexpected error during appeal approval: {e}"
        print(error_message)
        bot.answer_callback_query(call.id, "❌ Неизвестная ошибка.", show_alert=True)
        bot.send_message(call.from_user.id, "⚠️ Произошла неизвестная ошибка. Пожалуйста, обратитесь к разработчику.")




@bot.message_handler(func=lambda message: message.text == "ℹ️ Узнать причину блокировки")
def show_block_reason(message):
    user_id = message.from_user.id
    
    try:
        # Получаем данные о блокировке пользователя
        cursor.execute("""
            SELECT block_reason, last_appeal_date, is_blocked 
            FROM users 
            WHERE user_id = ?
        """, (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data or not user_data[2]:  # Если пользователь не заблокирован
            bot.send_message(
                user_id,
                "⚠️ Вы не заблокированы или информация о блокировке отсутствует.",
                reply_markup=user_main_menu
            )
            return
        
        block_reason, last_appeal_date, _ = user_data
        
        # Формируем ответное сообщение
        response = "⚠️ Информация о вашей блокировке:\n"
        response += f"❌ Причина: {block_reason}\n"
        
        # Добавляем дату последнего обжалования, если есть
        if last_appeal_date:
            response += f"⏳ Последнее обжалование: {last_appeal_date}\n"
        
        # Проверяем возможность подачи нового обжалования
        if last_appeal_date:
            last_appeal_date_obj = datetime.strptime(last_appeal_date, "%Y-%m-%d")
            if datetime.now() - last_appeal_date_obj < timedelta(days=3):
                response += (
                    "⏳ Вы можете подать новое обжалование только через 3 дня после последнего.\n"
                )
            else:
                response += (
                    "⚖️ Вы можете подать новое обжалование прямо сейчас.\n"
                )
        else:
            response += (
                "⚖️ Вы можете подать обжалование прямо сейчас.\n"
            )
        
        # Отправляем сообщение с информацией
        bot.send_message(user_id, response, reply_markup=user_blocked_menu)
    
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при получении информации о блокировке. Попробуйте позже.")
        print(f"Database error in show_block_reason: {e}")


#######
# Кнопка "➖ Удалить агента"
#######
@bot.message_handler(func=lambda message: message.text == "➖ Удалить агента")
def remove_agent(message):
    """
    Обработчик кнопки "➖ Удалить агента"
    Позволяет администратору удалить агента из персонала
    Только для администраторов
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа (только администраторы могут использовать эту команду)
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff or staff[0] != "admin":
        bot.send_message(user_id, 
                         "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    # Запрашиваем ID агента для удаления
    bot.send_message(user_id, 
                     "🆔 Введите ID агента, которого хотите удалить:")
    bot.register_next_step_handler(message, process_remove_agent)

def process_remove_agent(message):
    """
    Обработка удаления агента
    """
    admin_id = message.from_user.id
    agent_id_input = message.text.strip()
    
    try:
        # Проверяем корректность ввода ID
        agent_id = int(agent_id_input)
        
        # Проверяем, существует ли агент в базе данных
        cursor.execute("SELECT role FROM staff WHERE user_id = ?", (agent_id,))
        agent = cursor.fetchone()
        
        if not agent:
            bot.send_message(admin_id, 
                             f"❌ Пользователь с ID {agent_id} не является агентом или администратором.")
            return
        
        # Запрещаем удаление администраторов
        if agent[0] == "admin":
            bot.send_message(admin_id, 
                             "❌ Нельзя удалить администратора.")
            return
        
        # Удаляем агента из таблицы staff
        cursor.execute("DELETE FROM staff WHERE user_id = ?", (agent_id,))
        conn.commit()
        
        # Уведомляем администратора об успешном удалении
        bot.send_message(admin_id, 
                         f"✅ Агент с ID {agent_id} успешно удалён!")
        
        # Уведомляем удалённого агента (если возможно)
        try:
            bot.send_message(
                agent_id,
                "⚠️ Вы были удалены из числа агентов службы поддержки.",
                reply_markup=user_main_menu  # Возвращаем обычное меню пользователя
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                admin_id,
                f"⚠️ Не удалось уведомить пользователя с ID {agent_id}: {e}"
            )
        
    except ValueError:
        bot.send_message(admin_id, 
                         "❌ Неверный формат ID. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(admin_id, 
                         "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error in remove_agent: {e}")


#######
# Кнопка "📊 Статистика"
#######
@bot.message_handler(func=lambda message: message.text == "📊 Статистика")
def show_statistics(message):
    """
    Обработчик кнопки "📊 Статистика"
    Показывает статистику системы:
    - Общее количество тикетов
    - Открытые тикеты
    - Закрытые тикеты
    - Заблокированные пользователи
    - Активные агенты и администраторы
    Доступно только для персонала (агентов и администраторов)
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(user_id, 
                         "⚠️ У вас нет доступа к статистике.", 
                         reply_markup=user_main_menu)
        return
    
    try:
        # Получаем общую статистику по тикетам
        cursor.execute("SELECT COUNT(*) FROM tickets")
        total_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'")
        open_tickets = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed'")
        closed_tickets = cursor.fetchone()[0]
        
        # Получаем статистику по пользователям
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
        blocked_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        # Получаем статистику по персоналу
        cursor.execute("SELECT COUNT(*) FROM staff WHERE role = 'admin'")
        total_admins = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM staff WHERE role = 'agent'")
        total_agents = cursor.fetchone()[0]
        
        # Формируем ответное сообщение
        response = "📊 Статистика системы:\n\n"
        response += f"📋 Всего тикетов: {total_tickets}\n"
        response += f"🟢 Открытых тикетов: {open_tickets}\n"
        response += f"🔴 Закрытых тикетов: {closed_tickets}\n\n"
        response += f"👥 Всего пользователей: {total_users}\n"
        response += f"🚫 Заблокированных пользователей: {blocked_users}\n\n"
        response += f"👑 Администраторов: {total_admins}\n"
        response += f"🎉 Агентов поддержки: {total_agents}\n"
        
        # Отправляем результат
        bot.send_message(user_id, 
                         response, 
                         reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при получении статистики. Попробуйте позже.", 
                         reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
        print(f"Database error in show_statistics: {e}")

#######
# Кнопка "👥 Список персонала"
#######
@bot.message_handler(func=lambda message: message.text == "👥 Список персонала")
def show_staff_list(message):
    """
    Обработчик кнопки "👥 Список персонала"
    Показывает список всех администраторов и агентов с их ID и username
    Доступно только для персонала (агентов и администраторов)
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(user_id, 
                         "⚠️ У вас нет доступа к списку персонала.", 
                         reply_markup=user_main_menu)
        return
    
    try:
        # Получаем список персонала с их ролями и username из таблицы users
        cursor.execute("""
            SELECT s.user_id, s.role, u.username 
            FROM staff s 
            LEFT JOIN users u ON s.user_id = u.user_id
            ORDER BY s.role DESC, s.user_id ASC
        """)
        staff_members = cursor.fetchall()
        
        if not staff_members:
            bot.send_message(user_id, 
                             "📋 Список персонала пуст.", 
                             reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
            return
        
        # Формируем списки по ролям
        admins = []
        agents = []
        for member in staff_members:
            staff_user_id, role, username = member
            username = f"@{username}" if username else "Нет тега"
            entry = f"  {username} - ID: {staff_user_id}"
            
            if role == "admin":
                admins.append(entry)
            elif role == "agent":
                agents.append(entry)
        
        # Формируем ответное сообщение
        response = "👥 Список персонала:\n\n"
        
        # Администраторы
        response += "👑 Администраторы:\n"
        if admins:
            response += "\n".join(admins) + "\n"
        else:
            response += "  Нет администраторов.\n"
        
        # Агенты
        response += "\n🎉 Агенты поддержки:\n"
        if agents:
            response += "\n".join(agents) + "\n"
        else:
            response += "  Нет агентов.\n"
        
        # Отправляем результат
        bot.send_message(user_id, 
                         response, 
                         reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при получении списка персонала. Попробуйте позже.", 
                         reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
        print(f"Database error in show_staff_list: {e}")



#######
# Команды
#######

@bot.message_handler(commands=["ahelp"])
def admin_help(message):
    """
    Обработчик команды /ahelp
    Показывает список доступных команд для администраторов и агентов
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(user_id, "⚠️ У вас нет прав для просмотра этой справки.")
        return
    
    role = staff[0]  # Роль пользователя (admin или agent)
    
    # Формируем список команд в зависимости от роли
    if role == "admin":
        response = (
            "👑 Справка для администраторов:\n\n"
            "/makeadmin <ID> - Назначить пользователя администратором.\n"
            "Пример: `/makeadmin 123456789`\n\n"
            "/removeadmin <ID> - Снять пользователя с должности администратора.\n"
            "Пример: `/removeadmin 123456789`\n\n"
            "/ban <ID> <причина> - Заблокировать пользователя.\n"
            "Пример: `/ban 123456789 Нарушение правил`\n\n"
            "/unban <ID> - Разблокировать пользователя.\n"
            "Пример: `/unban 123456789`\n\n"
            "/ask <номер тикета> - Получить информацию о тикете.\n"
            "Пример: `/ask 42`\n\n"
            "➕ Добавить агента - Добавить нового агента через меню.\n"
            "➖ Удалить агента - Удалить агента через меню.\n"
            "📋 Список тикетов - Просмотреть список открытых тикетов.\n"
            "👥 Список персонала - Просмотреть список администраторов и агентов.\n"
            "📊 Статистика - Просмотреть статистику системы.\n"
            "⚖️ Обжалования - Просмотреть список обжалований."
        )
    elif role == "agent":
        response = (
            "🎉 Справка для агентов:\n\n"
            "/ask <номер тикета> - Получить информацию о тикете.\n"
            "Пример: `/ask 42`\n\n"
            "📋 Список тикетов - Просмотреть список открытых тикетов.\n"
            "👥 Список персонала - Просмотреть список администраторов и агентов.\n"
            "📊 Статистика - Просмотреть статистику системы.\n"
            "⚖️ Обжалования - Просмотреть список обжалований."
        )
    
    # Отправляем ответ
    bot.send_message(user_id, response, parse_mode="Markdown")

#######
# Команда /ask
#######
@bot.message_handler(commands=["ask"])
def get_ticket_info(message):
    """
    Обработчик команды /ask
    Позволяет запросить информацию о тикете
    Доступно для агентов и администраторов
    Формат: /ask <номер тикета>
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа (для агентов и администраторов)
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(user_id, 
                         "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    # Разбор аргументов команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(user_id, 
                         "❌ Неверный формат команды.\nИспользуйте: /ask <номер тикета>")
        return
    
    try:
        ticket_id = int(args[1])  # Получаем номер тикета
        
        # Получаем данные тикета из базы данных
        cursor.execute("""
            SELECT t.ticket_id, t.user_id, t.message, t.status, u.username 
            FROM tickets t
            LEFT JOIN users u ON t.user_id = u.user_id
            WHERE t.ticket_id = ?
        """, (ticket_id,))
        ticket_data = cursor.fetchone()
        
        if not ticket_data:
            bot.send_message(user_id, 
                             f"❌ Тикет с номером {ticket_id} не найден.")
            return
        
        ticket_id, creator_user_id, message, status, username = ticket_data
        username = f"@{username}" if username else "Unknown"
        
        # Если тикет закрыт, показываем только информацию
        if status == "closed":
            response = (
                f"🔒 Закрытый тикет #{ticket_id}:\n"
                f"👤 Создатель: {username} (ID: {creator_user_id})\n"
                f"📋 Сообщение: {message}\n"
                f"📊 Статус: Закрыт"
            )
            bot.send_message(user_id, response)
            return
        
        # Формируем ответное сообщение
        response = (
            f"🚨 Тикет #{ticket_id} от пользователя {username} (ID: {creator_user_id}):\n"
            f"{message}"
        )
        
        # Создаем клавиатуру с действиями
        keyboard = InlineKeyboardMarkup()
        
        # Только администраторы могут блокировать пользователей
        if staff[0] == "admin":
            keyboard.row(
                InlineKeyboardButton("🛑 Блокировать", callback_data=f"block_{ticket_id}_{creator_user_id}")
            )
        
        # Все персонал может ответить или закрыть тикет
        keyboard.row(
            InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{ticket_id}_{creator_user_id}"),
            InlineKeyboardButton("❌ Закрыть", callback_data=f"close_{ticket_id}_{creator_user_id}")
        )
        
        # Отправляем результат
        bot.send_message(user_id, response, reply_markup=keyboard)
        
    except ValueError:
        bot.send_message(user_id, 
                         "❌ Неверный формат номера тикета. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error in /ask: {e}")



@bot.message_handler(commands=["start"])
def start(message):
    """
    Обработчик команды /start
    Регистрирует пользователя, проверяет статус блокировки и роль
    """
    user_id = message.from_user.id
    username = message.from_user.username
    
    # Добавляем пользователя в базу
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    
    # Проверяем и создаем первого администратора
    create_first_admin(message)
    
    # Проверяем статус пользователя
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user and user[0]:  # Если заблокирован
        bot.send_message(
            user_id,
            "❌ Ваш аккаунт временно заблокирован. Для получения подробной информации используйте меню ниже:",
            reply_markup=user_blocked_menu
        )
    else:
        # Проверяем роль пользователя
        cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
        staff = cursor.fetchone()
        if staff:
            role = staff[0]
            if role == "admin":
                bot.send_message(
                    user_id,
                    "👑 Добро пожаловать, Администратор! 🌟\nИспользуйте меню для управления системой:",
                    reply_markup=admin_menu
                )
            elif role == "agent":
                bot.send_message(
                    user_id,
                    "🎉 Добро пожаловать, Агент поддержки! 🌟\nИспользуйте меню для работы с тикетами:",
                    reply_markup=agent_menu
                )
        else:
            # Обычный пользователь
            bot.send_message(
                user_id,
                "👋 Добро пожаловать в службу поддержки! 🌟\nЗдесь вы можете создавать тикеты и получать помощь.",
                reply_markup=user_main_menu
            )

@bot.message_handler(commands=["ban"])
def ban_user_command(message):
    """
    Команда для блокировки пользователя
    Только для администраторов
    Формат: /ban <ID> <причина>
    """
    user_id = message.from_user.id
    
    # Проверка прав
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff or staff[0] != "admin": #Тут можете убрать  or staff[0] != "admin" и она будет доступна и для агентов
        bot.send_message(message.chat.id, "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат команды.\nИспользуйте: /ban <ID пользователя> <причина>")
        return
    
    try:
        target_user_id = int(args[1])
        reason = args[2]
        
        # Блокировка
        cursor.execute("UPDATE users SET is_blocked = 1, block_reason = ? WHERE user_id = ?", 
                      (reason, target_user_id))
        conn.commit()
        
        bot.send_message(message.chat.id, 
                         f"✅ Пользователь с ID {target_user_id} успешно заблокирован.\nПричина: {reason}")
        
        # Уведомление пользователя
        try:
            bot.send_message(
                target_user_id,
                f"❌ Ваш аккаунт был заблокирован.\nПричина: {reason}\n\n"
                "Вы можете подать обжалование через меню.",
                reply_markup=user_blocked_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                message.chat.id,
                f"⚠️ Не удалось уведомить пользователя с ID {target_user_id}: {e}"
            )
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат ID. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(message.chat.id, "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error: {e}")

@bot.message_handler(commands=["unban"])
def unban_user_command(message):
    user_id = message.from_user.id
    # Проверка прав администратора
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff or staff[0] != "admin":
        bot.send_message(message.chat.id, "⚠️ У вас нет прав для выполнения этой команды.")
        return
    # Разбор аргументов команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Неверный формат команды. Используйте: /unban <ID>")
        return
    try:
        target_user_id = int(args[1])
        # Разблокировка пользователя и сброс cooldown
        cursor.execute("""
            UPDATE users 
            SET is_blocked = 0, block_reason = NULL, last_appeal_date = NULL 
            WHERE user_id = ?
        """, (target_user_id,))
        conn.commit()
        # Уведомление администратора
        bot.send_message(message.chat.id, f"✅ Пользователь с ID {target_user_id} успешно разблокирован.")
        # Уведомление пользователя (если возможно)
        try:
            bot.send_message(
                target_user_id,
                "✅ Вы были разблокированы. Теперь вы можете подавать обжалования.",
                reply_markup=user_main_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                message.chat.id,
                f"⚠️ Не удалось уведомить пользователя с ID {target_user_id}: {e}"
            )
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат ID. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(message.chat.id, "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error: {e}")


#######
# Кнопки и их обработчики
#######
@bot.message_handler(func=lambda message: message.text == "📝 Создать тикет")
def create_ticket(message):
    """
    Обработчик кнопки "Создать тикет"
    Проверяет статус блокировки и запрашивает описание проблемы
    """
    user_id = message.from_user.id
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user and user[0]:
        bot.send_message(user_id, 
                         "❌ Вы не можете создавать тикеты, так как ваш аккаунт заблокирован.")
    else:
        bot.send_message(user_id, 
                         "📝 Опишите вашу проблему или вопрос:")
        bot.register_next_step_handler(message, process_ticket_creation)

def process_ticket_creation(message):
    """
    Обработка создания тикета
    Сохраняет тикет в базу и уведомляет персонал
    """
    user_id = message.from_user.id
    ticket_message = message.text
    
    try:
        # Добавление тикета в базу
        cursor.execute("INSERT INTO tickets (user_id, message) VALUES (?, ?)", 
                      (user_id, ticket_message))
        ticket_id = cursor.lastrowid
        conn.commit()
        
        # Создание инлайн-клавиатуры
        keyboard = InlineKeyboardMarkup()
        keyboard.row(
            InlineKeyboardButton("🛑 Заблокировать", callback_data=f"block_{ticket_id}_{user_id}"),
            InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{ticket_id}_{user_id}")
        )
        keyboard.row(
            InlineKeyboardButton("❌ Закрыть", callback_data=f"close_{ticket_id}_{user_id}")
        )
        
        # Уведомление персонала
        cursor.execute("SELECT user_id, role FROM staff")
        staff_members = cursor.fetchall()
        notification_message = (
            f"🚨 Новый тикет #{ticket_id} от @{message.from_user.username or 'Unknown'}:\n"
            f"{ticket_message}"
        )
        for member in staff_members:
            staff_id, role = member
            try:
                bot.send_message(staff_id, notification_message, reply_markup=keyboard)
            except telebot.apihelper.ApiTelegramException as e:
                print(f"Ошибка отправки сообщения пользователю {staff_id}: {e}")
        
        bot.send_message(user_id, 
                         f"✅ Ваш тикет #{ticket_id} успешно создан!\n"
                         "Ожидайте ответа от службы поддержки.", 
                         reply_markup=telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
                         .row("❌ Закрыть тикет").row("✏️ Редактировать тикет").row("🏠 Главное меню"))
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Произошла ошибка при создании тикета. Попробуйте позже.")
        print(f"Database error: {e}")

@bot.message_handler(func=lambda message: message.text == "📜 История тикетов")
def ticket_history(message):
    """
    Обработчик кнопки "История тикетов"
    Показывает историю тикетов пользователя
    """
    user_id = message.from_user.id
    cursor.execute("SELECT * FROM tickets WHERE user_id = ?", (user_id,))
    tickets = cursor.fetchall()
    
    if not tickets:
        bot.send_message(user_id, 
                         "📭 У вас пока нет истории тикетов.", 
                         reply_markup=user_main_menu)
        return
    
    response = "📜 История ваших тикетов:\n"
    for ticket in tickets:
        ticket_id = ticket[0]
        message_text = ticket[2]
        status = ticket[3]
        created_at = ticket[5]
        closed_at = ticket[6]
        close_reason = ticket[7]
        
        response += (
            f"\n#{ticket_id} | Статус: {status} | Создан: {created_at}\n"
            f"📋 Сообщение: {message_text[:50]}{'...' if len(message_text) > 50 else ''}\n"
        )
        if closed_at:
            response += f"🔒 Закрыт: {closed_at} | Причина: {close_reason or 'Не указана'}\n"
        response += "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    
    bot.send_message(user_id, response, reply_markup=user_main_menu)

@bot.message_handler(func=lambda message: message.text == "⚖️ Подать обжалование")
def appeal_block(message):
    """
    Обработчик кнопки "Подать обжалование"
    Проверяет возможность подачи обжалования и запрашивает причину
    """
    user_id = message.from_user.id
    try:
        # Проверяем статус блокировки и дату последнего обжалования
        cursor.execute("SELECT is_blocked, block_reason, last_appeal_date FROM users WHERE user_id = ?", (user_id,))
        user_data = cursor.fetchone()
        if not user_data or not user_data[0]:
            bot.send_message(user_id, 
                             "❌ Вы не заблокированы, обжалование не требуется.", 
                             reply_markup=user_main_menu)
            return
        
        is_blocked, block_reason, last_appeal = user_data
        
        # Проверяем, можно ли подать новое обжалование
        if last_appeal:
            last_appeal_date = datetime.strptime(last_appeal, "%Y-%m-%d")
            if datetime.now() - last_appeal_date < timedelta(days=3):
                bot.send_message(
                    user_id,
                    "⏳ Вы можете подать обжалование только раз в 3 дня.\n"
                    "Попробуйте позже.",
                    reply_markup=user_blocked_menu
                )
                return
        
        # Находим последний тикет пользователя
        cursor.execute("SELECT ticket_id, message FROM tickets WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
        ticket = cursor.fetchone()
        if not ticket:
            bot.send_message(
                user_id,
                "❌ Не удалось найти тикет, связанный с вашей блокировкой.",
                reply_markup=user_blocked_menu
            )
            return
        
        ticket_id, ticket_message = ticket
        
        # Запрашиваем причину обжалования
        bot.send_message(
            user_id,
            f"📝 Причина вашей блокировки: {block_reason}\n"
            f"🔗 Последний тикет #{ticket_id}: {ticket_message}\n"
            "Введите причину обжалования:",
            reply_markup=user_blocked_menu
        )
        bot.register_next_step_handler(message, lambda m: process_appeal(m, ticket_id))
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при подаче обжалования. Попробуйте позже.", 
                         reply_markup=user_blocked_menu)
        print(f"Database error: {e}")

def process_appeal(message, ticket_id):
    """
    Обработка подачи обжалования
    """
    user_id = message.from_user.id
    reason = message.text
    
    try:
        # Сохраняем обжалование
        cursor.execute("INSERT INTO appeals (user_id, reason, related_ticket_id) VALUES (?, ?, ?)", 
                      (user_id, reason, ticket_id))
        cursor.execute("UPDATE users SET last_appeal_date = ? WHERE user_id = ?", 
                      (datetime.now().strftime("%Y-%m-%d"), user_id))
        conn.commit()
        
        # Уведомляем персонал
        cursor.execute("SELECT user_id FROM staff")
        staff_members = cursor.fetchall()
        for member in staff_members:
            bot.send_message(member[0], 
                            f"⚖️ Новое обжалование от @{message.from_user.username}:\n"
                            f"🔗 Тикет #{ticket_id}: {reason}")
        
        bot.send_message(user_id, 
                         "✅ Ваше обжалование отправлено! 📬\n"
                         "Ожидайте решения администрации.", 
                         reply_markup=user_blocked_menu)
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при отправке обжалования. Попробуйте позже.", 
                         reply_markup=user_blocked_menu)
        print(f"Database error: {e}")

@bot.message_handler(func=lambda message: message.text == "➕ Добавить агента")
def add_agent(message):
    """
    Обработчик кнопки "Добавить агента"
    Только для администраторов
    """
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (message.from_user.id,))
    staff = cursor.fetchone()
    if not staff or staff[0] != "admin":
        bot.send_message(message.chat.id, 
                         "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    bot.send_message(message.chat.id, 
                     "🆔 Введите ID пользователя, которого хотите назначить агентом:")
    bot.register_next_step_handler(message, process_add_agent)

def process_add_agent(message):
    """
    Обработка добавления агента
    """
    agent_id = message.text.strip()
    try:
        agent_id = int(agent_id)
        cursor.execute("INSERT INTO staff (user_id, role) VALUES (?, ?)", 
                      (agent_id, "agent"))
        conn.commit()
        
        bot.send_message(message.chat.id, 
                         f"✅ Пользователь с ID {agent_id} назначен агентом!")
        
        # Уведомляем нового агента
        try:
            bot.send_message(
                agent_id,
                "🎉 Поздравляем! Вы были назначены агентом службы поддержки! 🌟\n"
                "Используйте меню ниже для работы с тикетами:",
                reply_markup=agent_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                message.chat.id,
                f"⚠️ Не удалось уведомить пользователя с ID {agent_id}: {e}"
            )
            
    except ValueError:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат ID. Попробуйте снова.")
    except sqlite3.Error as e:
        bot.send_message(message.chat.id, 
                         "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error: {e}")

@bot.message_handler(func=lambda message: message.text == "📋 Список тикетов")
def show_ticket_list(message):
    """
    Обработчик кнопки "Список тикетов"
    Показывает список открытых тикетов с постраничной навигацией
    """
    user_id = message.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.send_message(user_id, 
                         "⚠️ У вас нет доступа к списку тикетов.")
        return
    
    try:
        # Получаем все открытые тикеты
        cursor.execute("""
            SELECT t.ticket_id, t.user_id, t.message, t.status, t.created_at, u.username 
            FROM tickets t
            LEFT JOIN users u ON t.user_id = u.user_id
            WHERE t.status = 'open'
            ORDER BY t.created_at ASC
        """)
        tickets = cursor.fetchall()
        
        if not tickets:
            bot.send_message(user_id, 
                             "📭 Нет открытых тикетов.", 
                             reply_markup=admin_menu if staff[0] == "admin" else agent_menu)
            return
        
        # Сохраняем тикеты в глобальную переменную для пагинации
        global current_tickets
        current_tickets = tickets
        
        # Показываем первую страницу
        show_ticket_page(user_id, 1, staff[0])
        
    except sqlite3.Error as e:
        bot.send_message(user_id, 
                         "❌ Ошибка при получении списка тикетов. Попробуйте позже.")
        print(f"Database error: {e}")

def show_ticket_page(user_id, page, role):
    """
    Отображение конкретной страницы списка тикетов
    """
    tickets_per_page = 5  # Количество тикетов на странице
    total_pages = (len(current_tickets) + tickets_per_page - 1) // tickets_per_page
    if page < 1 or page > total_pages:
        bot.send_message(user_id, 
                         "⚠️ Неверный номер страницы.")
        return
    
    start_index = (page - 1) * tickets_per_page
    end_index = start_index + tickets_per_page
    tickets_on_page = current_tickets[start_index:end_index]
    
    response = f"📋 Список открытых тикетов (Страница {page}/{total_pages}):\n"
    for ticket in tickets_on_page:
        ticket_id, user_id_ticket, message, status, created_at, username = ticket
        username = f"@{username}" if username else "Нет тега"
        response += (
            f"\n📌 #{ticket_id} | 🕒 {created_at}\n"
            f"👤 {username} ({user_id_ticket})\n"
            f"📋 {message[:50]}{'...' if len(message) > 50 else ''}\n"
            f"📊 Статус: {status}\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        )
    
    # Создаем клавиатуру для навигации
    keyboard = telebot.types.InlineKeyboardMarkup()
    if page > 1:
        keyboard.add(telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data=f"tickets_page_{page - 1}"))
    if page < total_pages:
        keyboard.add(telebot.types.InlineKeyboardButton("➡️ Вперед", callback_data=f"tickets_page_{page + 1}"))
    
    bot.send_message(user_id, response, reply_markup=keyboard)

#######
# Обработчики callback-запросов
#######
@bot.callback_query_handler(func=lambda call: call.data.startswith("tickets_page_"))
def handle_ticket_pagination(call):
    """
    Обработчик кнопок навигации по страницам тикетов
    """
    page = int(call.data.split("_")[-1])
    user_id = call.from_user.id
    
    # Проверка прав доступа
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    staff = cursor.fetchone()
    if not staff:
        bot.answer_callback_query(call.id, 
                                  "⚠️ У вас нет доступа к этому действию.")
        return
    
    # Показываем запрошенную страницу
    show_ticket_page(user_id, page, staff[0])

@bot.callback_query_handler(func=lambda call: call.data.startswith(('block_', 'reply_', 'close_')))
def handle_ticket_callback(call):
    """
    Обработчик действий с тикетами (блокировка, ответ, закрытие)
    """
    try:
        data = call.data.split('_')
        action = data[0]
        ticket_id = int(data[1])
        user_id = int(data[2])
        
        # Проверка прав доступа
        cursor.execute("SELECT role FROM staff WHERE user_id = ?", (call.from_user.id,))
        staff = cursor.fetchone()
        if not staff:
            bot.answer_callback_query(call.id, 
                                      "❌ У вас нет доступа к этим действиям.")
            return
        
        # Получение информации о тикете
        cursor.execute("""
            SELECT message, status 
            FROM tickets 
            WHERE ticket_id = ?
        """, (ticket_id,))
        ticket_data = cursor.fetchone()
        if not ticket_data:
            bot.answer_callback_query(call.id, 
                                      "❌ Тикет не найден.")
            return
        
        ticket_message, ticket_status = ticket_data
        if ticket_status != 'open':
            bot.answer_callback_query(call.id, 
                                      "❌ Тикет уже закрыт.")
            return
        
        if action == "block":
            if staff[0] != "admin":
                bot.answer_callback_query(call.id, 
                                          "❌ Только администраторы могут блокировать пользователей.")
                return
            
            # Запрашиваем причину блокировки
            bot.send_message(call.message.chat.id, 
                             "📝 Укажите причину блокировки:")
            bot.register_next_step_handler(call.message, 
                                           lambda m: process_block_from_ticket(m, user_id, ticket_id, call))
            
        elif action == "reply":
            # Запрашиваем ответ на тикет
            bot.send_message(call.message.chat.id, 
                             "💬 Введите ваш ответ на тикет:")
            bot.register_next_step_handler(call.message, 
                                           lambda m: process_reply_to_ticket(m, user_id, ticket_id, call))
            
        elif action == "close":
            if staff[0] != "admin":
                bot.answer_callback_query(call.id, 
                                          "❌ Только администраторы могут закрывать тикеты.")
                return
            
            # Запрашиваем причину закрытия
            bot.send_message(call.message.chat.id, 
                             "📝 Укажите причину закрытия тикета:")
            bot.register_next_step_handler(call.message, 
                                           lambda m: process_close_ticket_admin(m, user_id, ticket_id, call))
            
    except ValueError:
        bot.answer_callback_query(call.id, 
                                  "❌ Неверный формат данных.")
    except Exception as e:
        bot.answer_callback_query(call.id, 
                                  "❌ Произошла ошибка при обработке запроса.")
        print(f"Error in ticket callback handler: {e}")

def process_block_from_ticket(message, user_id, ticket_id, call):
    """
    Обработка блокировки пользователя из тикета
    """
    try:
        reason = message.text
        
        # Блокируем пользователя
        cursor.execute("""
            UPDATE users 
            SET is_blocked = 1, block_reason = ?, last_appeal_date = NULL 
            WHERE user_id = ?
        """, (reason, user_id))
        
        # Закрываем тикет
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, close_reason = ? 
            WHERE ticket_id = ?
        """, (f"Пользователь заблокирован: {reason}", ticket_id))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            bot.send_message(
                user_id,
                f"❌ Вы были заблокированы.\nПричина: {reason}",
                reply_markup=user_blocked_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        
        # Обновляем сообщение персонала
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n"
                 f"✅ Пользователь успешно заблокирован.\n"
                 f"Причина: {reason}",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, 
                                  "✅ Пользователь успешно заблокирован.")
        
    except sqlite3.Error as e:
        conn.rollback()
        bot.answer_callback_query(call.id, 
                                  "❌ Ошибка при блокировке пользователя.")
        print(f"Database error during block: {e}")

def process_reply_to_ticket(message, user_id, ticket_id, call):
    """
    Обработка ответа на тикет
    """
    try:
        reply_text = message.text
        
        # Отправляем ответ пользователю
        try:
            bot.send_message(
                user_id,
                f"💬 Ответ на ваш тикет #{ticket_id}:\n"
                f"{reply_text}",
                reply_markup=user_main_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка отправки ответа пользователю {user_id}: {e}")
        
        # Автоматически закрываем тикет
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, close_reason = ? 
            WHERE ticket_id = ?
        """, ("Тикет закрыт после ответа агента", ticket_id))
        conn.commit()
        
        # Обновляем сообщение персонала
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n"
                 f"✅ Ответ успешно отправлен:\n"
                 f"{reply_text}",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, 
                                  "✅ Ответ отправлен, тикет закрыт.")
        
    except sqlite3.Error as e:
        conn.rollback()
        bot.answer_callback_query(call.id, 
                                  "❌ Ошибка при отправке ответа.")
        print(f"Database error during reply: {e}")

def process_close_ticket_admin(message, user_id, ticket_id, call):
    """
    Обработка закрытия тикета администратором
    """
    try:
        reason = message.text
        
        # Закрываем тикет
        cursor.execute("""
            UPDATE tickets 
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, close_reason = ? 
            WHERE ticket_id = ?
        """, (reason, ticket_id))
        conn.commit()
        
        # Уведомляем пользователя
        try:
            bot.send_message(
                user_id,
                f"❌ Ваш тикет #{ticket_id} закрыт.\nПричина: {reason}",
                reply_markup=user_main_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            print(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
        
        # Обновляем сообщение персонала
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"{call.message.text}\n"
                 f"✅ Тикет успешно закрыт.\n"
                 f"Причина: {reason}",
            reply_markup=None
        )
        bot.answer_callback_query(call.id, 
                                  "✅ Тикет успешно закрыт.")
        
    except sqlite3.Error as e:
        conn.rollback()
        bot.answer_callback_query(call.id, 
                                  "❌ Ошибка при закрытии тикета.")
        print(f"Database error during close: {e}")

#######
# Вспомогательные функции
#######
def create_first_admin(message):
    """
    Создание первого администратора при старте бота
    Если таблица staff пустая, первый пользователь становится админом
    """
    try:
        cursor.execute("SELECT COUNT(*) FROM staff")
        staff_count = cursor.fetchone()[0]
        if staff_count == 0:
            first_admin_id = message.from_user.id
            cursor.execute("INSERT INTO staff (user_id, role) VALUES (?, ?)", 
                          (first_admin_id, "admin"))
            conn.commit()
            bot.send_message(
                first_admin_id,
                "👑 Вы были назначены первым администратором! 🎉\n"
                "Используйте меню ниже для управления системой:",
                reply_markup=admin_menu
            )
            print(f"Первый администратор добавлен: {first_admin_id}")
    except sqlite3.Error as e:
        print(f"Ошибка при создании первого администратора: {e}")


#######
# Команды управления администраторами
#######
@bot.message_handler(commands=["makeadmin"])
def make_admin_command(message):
    """
    Команда для назначения нового администратора
    Только для существующих администраторов
    Формат: /makeadmin <ID>
    """
    user_id = message.from_user.id
    
    # Проверка прав текущего пользователя
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    current_user = cursor.fetchone()
    if not current_user or current_user[0] != "admin":
        bot.send_message(message.chat.id, 
                         "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    # Разбор аргументов команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат команды.\nИспользуйте: /makeadmin <ID пользователя>")
        return
    
    try:
        target_user_id = int(args[1])
        
        # Проверяем, существует ли пользователь в базе
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (target_user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            bot.send_message(message.chat.id, 
                             f"❌ Пользователь с ID {target_user_id} не найден в системе.")
            return
        
        # Проверяем, не является ли пользователь уже администратором
        cursor.execute("SELECT role FROM staff WHERE user_id = ?", (target_user_id,))
        existing_staff = cursor.fetchone()
        if existing_staff and existing_staff[0] == "admin":
            bot.send_message(message.chat.id, 
                             f"⚠️ Пользователь с ID {target_user_id} уже является администратором.")
            return
        
        # Добавляем или обновляем роль пользователя
        cursor.execute("""
            INSERT INTO staff (user_id, role) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET role = excluded.role
        """, (target_user_id, "admin"))
        conn.commit()
        
        # Уведомляем текущего администратора
        bot.send_message(message.chat.id, 
                         f"✅ Пользователь с ID {target_user_id} успешно назначен администратором.")
        
        # Уведомляем нового администратора
        try:
            bot.send_message(
                target_user_id,
                "👑 Вы были назначены администратором службы поддержки! 🎉\n"
                "Используйте меню ниже для управления системой:",
                reply_markup=admin_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                message.chat.id,
                f"⚠️ Не удалось уведомить нового администратора: {e}"
            )
            
    except ValueError:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат ID. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(message.chat.id, 
                         "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error: {e}")

@bot.message_handler(commands=["removeadmin"])
def remove_admin_command(message):
    """
    Команда для снятия администратора
    Только для существующих администраторов
    Формат: /removeadmin <ID>
    """
    user_id = message.from_user.id
    
    # Проверка прав текущего пользователя
    cursor.execute("SELECT role FROM staff WHERE user_id = ?", (user_id,))
    current_user = cursor.fetchone()
    if not current_user or current_user[0] != "admin":
        bot.send_message(message.chat.id, 
                         "⚠️ У вас нет прав для выполнения этой команды.")
        return
    
    # Разбор аргументов команды
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат команды.\nИспользуйте: /removeadmin <ID пользователя>")
        return
    
    try:
        target_user_id = int(args[1])
        
        # Проверяем, является ли пользователь администратором
        cursor.execute("SELECT role FROM staff WHERE user_id = ?", (target_user_id,))
        target_user = cursor.fetchone()
        if not target_user or target_user[0] != "admin":
            bot.send_message(message.chat.id, 
                             f"❌ Пользователь с ID {target_user_id} не является администратором.")
            return
        
        # Удаляем роль администратора
        cursor.execute("DELETE FROM staff WHERE user_id = ?", (target_user_id,))
        conn.commit()
        
        # Уведомляем текущего администратора
        bot.send_message(message.chat.id, 
                         f"✅ Пользователь с ID {target_user_id} больше не является администратором.")
        
        # Уведомляем бывшего администратора
        try:
            bot.send_message(
                target_user_id,
                "⚠️ Вы были сняты с должности администратора.\n"
                "Теперь у вас нет доступа к административным функциям.",
                reply_markup=user_main_menu
            )
        except telebot.apihelper.ApiTelegramException as e:
            bot.send_message(
                message.chat.id,
                f"⚠️ Не удалось уведомить бывшего администратора: {e}"
            )
            
    except ValueError:
        bot.send_message(message.chat.id, 
                         "❌ Неверный формат ID. Пожалуйста, укажите числовое значение.")
    except sqlite3.Error as e:
        bot.send_message(message.chat.id, 
                         "❌ Ошибка базы данных. Попробуйте позже.")
        print(f"Database error: {e}")

#######
# Запуск бота
#######
if __name__ == "__main__":
    print("Бот запущен...")
    bot.polling(non_stop=True, timeout=120)