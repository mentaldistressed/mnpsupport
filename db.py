import sqlite3
from datetime import datetime
from config import DATABASE_FILE

def initialize_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute('''CREATE TABLE IF NOT EXISTS tickets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        status TEXT,
                        message TEXT,
                        response TEXT,
                        username TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ticket_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER,
                        sender TEXT,
                        message TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        agent_id INTEGER,
                        user_message_id INTEGER
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS attachments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        ticket_id INTEGER,
                        file_id TEXT
                      )''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS blocks (
        user_id INTEGER PRIMARY KEY,
        reason TEXT
    )
    ''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    short_id TEXT UNIQUE,
    file_id TEXT UNIQUE
);
''')
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT
);''')

    conn.commit()
    cursor.close()
    conn.close()

def get_ticket_by_id(ticket_id):
    conn = sqlite3.connect('support.db')
    cursor = conn.cursor()

    cursor.execute("SELECT id, user_id, status, message, username FROM tickets WHERE id = ?", (ticket_id,))
    
    ticket = cursor.fetchone()

    conn.close()

    if ticket:
        return {
            'ticket_id': ticket[0],
            'user_id': ticket[1],
            'status': ticket[2],
            'message': ticket[3],
            'username': ticket[4]
        }
    else:
        return None

def get_tickets_by_user(user_id: int):
    conn = sqlite3.connect('support.db')
    cursor = conn.cursor()

    try:
        query = """
            SELECT id, user_id, status, message, response, username
            FROM tickets
            WHERE user_id = ?
        """
        cursor.execute(query, (user_id,))
        return cursor.fetchall()
    except Exception as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return []

def delete_message_from_history(message_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ticket_history WHERE user_message_id = ?", (message_id,))
    conn.commit()
    cursor.close()
    conn.close()

def get_message_info(message_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_message_id, ticket_id FROM ticket_history WHERE id = ?", (message_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return (True, result[0], result[1]) if result else (False, None, None)

def edit_ticket_message(message_id, new_message):
    conn = sqlite3.connect('support.db')
    cursor = conn.cursor()
    
    cursor.execute(
        '''SELECT user_message_id, ticket_id FROM ticket_history WHERE id = ? AND sender = 'agent' ''',
        (message_id,)
    )
    result = cursor.fetchone()
    if not result:
        return False, None, None
    
    user_message_id, ticket_id = result

    cursor.execute(
        '''UPDATE ticket_history
        SET message = ?
        WHERE id = ? AND sender = 'agent' ''',
        (new_message, message_id)
    )
    conn.commit()

    return True, user_message_id, ticket_id

def get_statistics():
    conn = sqlite3.connect('support.db')
    cursor = conn.cursor()

    statistics = {}

    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = '1'")
    statistics['open_tickets'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = '2'")
    statistics['in_process_tickets'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT id FROM tickets WHERE status = '2'")
    statistics['in_process_ticket_ids'] = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT id FROM tickets WHERE status = '1'")
    statistics['open_ticket_ids'] = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = '3'")
    statistics['closed_tickets'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tickets")
    statistics['total_tickets'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM tickets")
    statistics['total_users'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ticket_history WHERE sender = 'agent'")
    statistics['agent_messages'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ticket_history WHERE sender = 'user'")
    statistics['user_messages'] = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM ticket_history")
    statistics['total_messages'] = cursor.fetchone()[0]

    conn.close()

    return statistics

def create_ticket(user_id, status, message, username):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tickets (user_id, status, message, username) VALUES (?, ?, ?, ?)', (user_id, status, message, username))
    ticket_id = cursor.lastrowid
    cursor.execute('INSERT INTO ticket_history (ticket_id, sender, message) VALUES (?, ?, ?)', (ticket_id, 'user', message))
    conn.commit()
    cursor.close()
    conn.close()
    return ticket_id

def get_ticket(ticket_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tickets WHERE id = ?', (ticket_id,))
    ticket = cursor.fetchone()
    cursor.close()
    conn.close()
    return ticket

def get_open_ticket(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM tickets WHERE user_id = ? AND status != ?', (user_id, '3'))
    ticket = cursor.fetchone()
    cursor.close()
    conn.close()
    return ticket

def add_message_to_ticket(ticket_id, sender, message, agent_id, user_message_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO ticket_history (ticket_id, sender, message, agent_id, user_message_id) VALUES (?, ?, ?, ?, ?)', 
                   (ticket_id, sender, message, agent_id, user_message_id))
    conn.commit()
    cursor.close()
    conn.close()
    return cursor.lastrowid

def add_attachment(ticket_id, file_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO attachments (ticket_id, file_id) VALUES (?, ?)', 
                   (ticket_id, file_id))
    conn.commit()
    cursor.close()
    conn.close()

def update_ticket_status(ticket_id, status):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('UPDATE tickets SET status = ? WHERE id = ?', (status, ticket_id))
    conn.commit()
    cursor.close()
    conn.close()

def get_all_tickets(status=None):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    if status:
        cursor.execute('SELECT id, user_id, status, message, username FROM tickets WHERE status = ?', (status,))
    else:
        cursor.execute('SELECT id, user_id, status, message, username FROM tickets')
    tickets = cursor.fetchall()
    cursor.close()
    conn.close()
    return tickets

def get_ticket_history(ticket_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM ticket_history WHERE ticket_id = ? ORDER BY timestamp', (ticket_id,))
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages

def get_ticket_attachments(ticket_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM attachments WHERE ticket_id = ?', (ticket_id,))
    attachments = cursor.fetchall()
    cursor.close()
    conn.close()
    return attachments

def get_user_by_id(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM tickets WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

def block_user(user_id, reason):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO blocks (user_id, reason) VALUES (?, ?)', (user_id, reason))
    conn.commit()
    cursor.close()
    conn.close()

def is_user_blocked(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM blocks WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result is not None

def get_block_reason(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT reason FROM blocks WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

def get_username_by_id(user_id):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM tickets WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result[0] if result else None

initialize_database()
