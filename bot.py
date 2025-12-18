import os
import time
from bson import ObjectId
from pymongo import MongoClient
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

ADMIN_IDS = [123456789]  # <-- PUT YOUR TELEGRAM USER ID
SUPPORT_USERNAME = "@YourSupportUsername"

BONUS_AMOUNT = 5
BONUS_COOLDOWN = 86400  # 24 hours
MIN_TIP = 1
MIN_WITHDRAW = 10
ACTION_COOLDOWN = 10  # seconds

# ================= DATABASE =================
client = MongoClient(MONGO_URI)
db = client["qwallet"]
users = db["users"]
withdraws = db["withdraws"]
transactions = db["transactions"]

# ================= MENUS =================
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["💰 Balance"],
        ["🎁 Bonus", "💸 Tip"],
        ["💵 Withdraw", "📜 History"],
        ["❓ Support"]
    ],
    resize_keyboard=True
)

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        ["👥 Users"],
        ["⬅ Back"]
    ],
    resize_keyboard=True
)

# ================= HELPERS =================
def get_user(uid, username):
    user = users.find_one({"user_id": uid})
    if not user:
        users.insert_one({
            "user_id": uid,
            "username": username,
            "balance": 0,
            "last_bonus": 0,
            "frozen": False
        })
        user = users.find_one({"user_id": uid})
    return user

def is_frozen(uid):
    user = users.find_one({"user_id": uid})
    return user and user.get("frozen", False)

def anti_spam(context):
    last = context.user_data.get("last_action", 0)
    if time.time() - last < ACTION_COOLDOWN:
        return False
    context.user_data["last_action"] = time.time()
    return True

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    get_user(u.id, u.username)
    await update.message.reply_text(
        "👋 Welcome to QWallet",
        reply_markup=MAIN_MENU
    )

# ================= USER FEATURES =================
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_frozen(uid):
        await update.message.reply_text("❄️ Your account is frozen")
        return

    user = get_user(uid, update.effective_user.username)
    await update.message.reply_text(
        f"💰 Your Wallet Balance\n\n"
        f"🔹 Total: {user['balance']} USDT"
    )

async def bonus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_frozen(uid):
        await update.message.reply_text("❄️ Your account is frozen")
        return

    user = get_user(uid, update.effective_user.username)
    now = int(time.time())

    if now - user.get("last_bonus", 0) < BONUS_COOLDOWN:
        remaining = BONUS_COOLDOWN - (now - user["last_bonus"])
        h = remaining // 3600
        m = (remaining % 3600) // 60
        await update.message.reply_text(
            f"⏳ Bonus already claimed\nTry again in {h}h {m}m"
        )
        return

    users.update_one(
        {"user_id": uid},
        {"$inc": {"balance": BONUS_AMOUNT}, "$set": {"last_bonus": now}}
    )

    transactions.insert_one({
        "user_id": uid,
        "type": "daily_bonus",
        "amount": BONUS_AMOUNT
    })

    await update.message.reply_text(
        f"🎁 Daily Bonus Claimed!\n+{BONUS_AMOUNT} USDT"
    )

async def tip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_frozen(update.effective_user.id):
        await update.message.reply_text("❄️ Your account is frozen")
        return

    context.user_data["tip_step"] = "user"
    await update.message.reply_text("Send USERNAME (without @)")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_frozen(update.effective_user.id):
        await update.message.reply_text("❄️ Your account is frozen")
        return

    context.user_data["withdraw_step"] = "amount"
    await update.message.reply_text("Enter withdraw amount (USDT)")

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txs = transactions.find({"user_id": uid}).sort("_id", -1).limit(10)

    msg = "📜 Transaction History\n\n"
    for t in txs:
        msg += f"• {t['type']} : {t['amount']} USDT\n"

    await update.message.reply_text(msg)

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆘 Support\n\nContact: {SUPPORT_USERNAME}"
    )

# ================= ADMIN =================
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id in ADMIN_IDS:
        await update.message.reply_text(
            "🛠 Admin Panel",
            reply_markup=ADMIN_MENU
        )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    msg = " ".join(context.args)
    for u in users.find():
        try:
            await context.bot.send_message(u["user_id"], msg)
        except:
            pass

async def freeze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set": {"frozen": True}})
    await update.message.reply_text("❄️ User frozen")

async def unfreeze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    uid = int(context.args[0])
    users.update_one({"user_id": uid}, {"$set": {"frozen": False}})
    await update.message.reply_text("✅ User unfrozen")

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text
    user = get_user(uid, update.effective_user.username)

    if not anti_spam(context):
        await update.message.reply_text("⏳ Please wait a bit")
        return

    # TIP FLOW
    if context.user_data.get("tip_step") == "user":
        context.user_data["tip_to"] = text
        context.user_data["tip_step"] = "amount"
        await update.message.reply_text("Enter tip amount")
        return

    if context.user_data.get("tip_step") == "amount":
        amount = float(text)
        if amount < MIN_TIP or user["balance"] < amount:
            await update.message.reply_text("❌ Invalid amount")
            context.user_data.clear()
            return

        receiver = users.find_one({"username": context.user_data["tip_to"]})
        if not receiver:
            await update.message.reply_text("❌ User not found")
            context.user_data.clear()
            return

        users.update_one({"user_id": uid}, {"$inc": {"balance": -amount}})
        users.update_one({"user_id": receiver["user_id"]}, {"$inc": {"balance": amount}})

        transactions.insert_one({
            "user_id": uid,
            "type": "tip_sent",
            "amount": amount
        })

        await update.message.reply_text("✅ Tip sent")
        context.user_data.clear()
        return

    # WITHDRAW FLOW
    if context.user_data.get("withdraw_step") == "amount":
        amount = float(text)
        if amount < MIN_WITHDRAW or user["balance"] < amount:
            await update.message.reply_text("❌ Invalid withdraw amount")
            context.user_data.clear()
            return

        users.update_one({"user_id": uid}, {"$inc": {"balance": -amount}})
        req = withdraws.insert_one({
            "user_id": uid,
            "username": user["username"],
            "amount": amount,
            "status": "pending"
        })

        transactions.insert_one({
            "user_id": uid,
            "type": "withdraw",
            "amount": amount
        })

        for admin in ADMIN_IDS:
            await context.bot.send_message(
                admin,
                f"💸 Withdraw Request\nUser: @{user['username']}\nAmount: {amount} USDT",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{req.inserted_id}"),
                        InlineKeyboardButton("❌ Reject", callback_data=f"reject_{req.inserted_id}")
                    ]
                ])
            )

        await update.message.reply_text("⏳ Withdraw request submitted")
        context.user_data.clear()
        return

# ================= CALLBACKS =================
async def withdraw_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, wid = query.data.split("_")
    wd = withdraws.find_one({"_id": ObjectId(wid)})
    if not wd:
        return

    if action == "approve":
        withdraws.update_one({"_id": ObjectId(wid)}, {"$set": {"status": "approved"}})
        await context.bot.send_message(wd["user_id"], "✅ Withdrawal approved")

    elif action == "reject":
        withdraws.update_one({"_id": ObjectId(wid)}, {"$set": {"status": "rejected"}})
        users.update_one({"user_id": wd["user_id"]}, {"$inc": {"balance": wd["amount"]}})
        await context.bot.send_message(
            wd["user_id"],
            "❌ Withdrawal rejected (amount refunded)"
        )

# ================= MAIN =================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("freeze", freeze))
    app.add_handler(CommandHandler("unfreeze", unfreeze))

    app.add_handler(MessageHandler(filters.Regex("💰 Balance"), balance))
    app.add_handler(MessageHandler(filters.Regex("🎁 Bonus"), bonus))
    app.add_handler(MessageHandler(filters.Regex("💸 Tip"), tip))
    app.add_handler(MessageHandler(filters.Regex("💵 Withdraw"), withdraw))
    app.add_handler(MessageHandler(filters.Regex("📜 History"), history))
    app.add_handler(MessageHandler(filters.Regex("❓ Support"), support))

    app.add_handler(CallbackQueryHandler(withdraw_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()

if __name__ == "__main__":
    main()


