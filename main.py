import sqlite3
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

BOT_TOKEN = "8799427894:AAFAhyWSwFxmhZ0uHwIMKtBsP9S8WSvOnUI"
ADMIN_ID = 6624597995

# 📦 DATABASE
conn = sqlite3.connect("bot.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS products(
    name TEXT PRIMARY KEY,
    price REAL,
    currency TEXT
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS orders(
    id TEXT PRIMARY KEY,
    user_id INTEGER,
    product TEXT,
    price REAL,
    currency TEXT,
    paid INTEGER DEFAULT 0
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS logs(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,
    message TEXT
)
""")

conn.commit()

ADMIN_STATE = {}

# 🌐 Crypto-prijs omrekenen
def euro_to_crypto(amount_eur, crypto="BTC"):
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={crypto.lower()}&vs_currencies=eur"
    r = requests.get(url).json()
    price = r.get(crypto.lower(), {}).get("eur", None)
    if price:
        return round(amount_eur / price, 8)
    return None

# 🔍 TX check
def check_tx(txid, expected_amount, address):
    url = f"https://blockstream.info/api/tx/{txid}"
    r = requests.get(url)
    if r.status_code != 200:
        return False
    data = r.json()
    total = sum(out["value"] / 100000000 for out in data["vout"]
                if out["scriptpubkey_address"] == address)
    return total >= expected_amount

def log_event(type_, message):
    c.execute("INSERT INTO logs(type, message) VALUES(?,?)", (type_, message))
    conn.commit()

# 🏠 START MENU
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🛒 Buy", callback_data="buy_menu")]]
    if update.effective_user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🧑‍💼 Admin Panel", callback_data="admin_panel")])
    keyboard.append([InlineKeyboardButton("📄 My Orders", callback_data="my_orders")])
    await update.message.reply_text("Welcome!", reply_markup=InlineKeyboardMarkup(keyboard))

# 🛒 BUY MENU
async def buy_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    c.execute("SELECT name, price, currency FROM products")
    products = c.fetchall()
    buttons = [[InlineKeyboardButton(f"{name} ({price} {currency})", callback_data=f"buy_{name}")]
               for name, price, currency in products]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="start")])
    await query.edit_message_text("Select product:", reply_markup=InlineKeyboardMarkup(buttons))

# 💰 BUY ACTION
async def handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_name = query.data.split("_")[1]
    c.execute("SELECT price, currency FROM products WHERE name=?", (product_name,))
    product = c.fetchone()
    if not product:
        await query.edit_message_text("Product not found")
        return
    price, currency = product
    address = "PUT_COIN_ADDRESS_HERE"  # Maak een mapping per coin voor multi-coin
    order_id = f"{query.from_user.id}_{product_name}"
    c.execute("INSERT OR REPLACE INTO orders(id, user_id, product, price, currency) VALUES(?,?,?,?,?)",
              (order_id, query.from_user.id, product_name, price, currency))
    conn.commit()
    await query.edit_message_text(f"""
💰 Send {price} {currency} to:

Address: {address}

After payment:
/paid {order_id} TXID
""")

# 💸 USER PAID
async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /paid order_id TXID")
        return
    order_id, txid = context.args[0], context.args[1]
    c.execute("SELECT user_id, product, price, currency, paid FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order:
        await update.message.reply_text("Order not found")
        return
    user_id, product, price, currency, paid_flag = order
    if paid_flag:
        await update.message.reply_text("Order already paid")
        return
    address = "PUT_COIN_ADDRESS_HERE"  # mapping per coin
    if check_tx(txid, price, address):
        c.execute("UPDATE orders SET paid=1 WHERE id=?", (order_id,))
        conn.commit()
        keyboard = [[InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_{order_id}")]]
        await context.bot.send_message(chat_id=ADMIN_ID,
                                       text=f"Payment verified\nOrder: {order_id}",
                                       reply_markup=InlineKeyboardMarkup(keyboard))
        await update.message.reply_text("✅ Payment detected, waiting for admin")
        log_event("payment_verified", f"{user_id} paid {product} ({price} {currency})")
    else:
        await update.message.reply_text("❌ Payment not valid")
        log_event("payment_rejected", f"{user_id} tried to pay {product} ({price} {currency}) TXID: {txid}")

# ✅ ADMIN CONFIRM BUTTON
async def confirm_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    order_id = query.data.split("_")[1]
    c.execute("SELECT user_id, product, paid FROM orders WHERE id=?", (order_id,))
    order = c.fetchone()
    if not order or order[2] == 0:
        await query.edit_message_text("Not paid")
        return
    user_id, product, _ = order
    await context.bot.send_message(chat_id=user_id, text=f"✅ Order confirmed: {product}")
    await query.edit_message_text("Order confirmed!")
    log_event("order_confirmed", f"Admin confirmed order {order_id} for user {user_id}")

# 🧑‍💼 ADMIN PANEL
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("➕ Add Product", callback_data="add_product")],
        [InlineKeyboardButton("📋 View Orders", callback_data="view_orders")],
        [InlineKeyboardButton("🗂 View Logs", callback_data="view_logs")]
    ]
    await query.edit_message_text("Admin Panel", reply_markup=InlineKeyboardMarkup(keyboard))

# ➕ ADD PRODUCT FLOW MET BACK KNOP
async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ADMIN_STATE[query.from_user.id] = "waiting_product"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]
    await query.edit_message_text(
        "Send product like:\nname price currency\nExample:\nspotify 0.0002 BTC",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# 📄 VIEW USER ORDERS
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    c.execute("SELECT id, product, paid, currency, price FROM orders WHERE user_id=?", (query.from_user.id,))
    orders = c.fetchall()
    if not orders:
        await query.edit_message_text("You have no orders yet")
        return
    text = "\n".join([f"{oid} - {prod} - {price} {curr} - {'Paid' if paid else 'Pending'}"
                      for oid, prod, paid, curr, price in orders])
    await query.edit_message_text(f"Your Orders:\n{text}")

# 📥 HANDLE ADMIN INPUT
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ADMIN_STATE and ADMIN_STATE[user_id] == "waiting_product":
        try:
            name, price, currency = update.message.text.split()
            c.execute("INSERT OR REPLACE INTO products(name, price, currency) VALUES(?,?,?)",
                      (name, float(price), currency.upper()))
            conn.commit()
            await update.message.reply_text(f"✅ Added {name} ({price} {currency.upper()})")
            ADMIN_STATE.pop(user_id)
        except:
            await update.message.reply_text("Invalid format, use: name price currency")

# 🚀 BOT START
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("paid", paid))
app.add_handler(CallbackQueryHandler(buy_menu, pattern="buy_menu"))
app.add_handler(CallbackQueryHandler(handle_buy, pattern="buy_"))
app.add_handler(CallbackQueryHandler(admin_panel, pattern="admin_panel"))
app.add_handler(CallbackQueryHandler(add_product, pattern="add_product"))
app.add_handler(CallbackQueryHandler(confirm_button, pattern="confirm_"))
app.add_handler(CallbackQueryHandler(my_orders, pattern="my_orders"))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
app.run_polling()