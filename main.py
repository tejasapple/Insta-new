import asyncio
import logging
import os
import random
from datetime import datetime
from typing import Any, Dict, List, Tuple

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command
from dotenv import load_dotenv
import motor.motor_asyncio
from motor.core import AgnosticCollection

# Load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Configure robust logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Verify environments
if not BOT_TOKEN or not MONGO_URI:
    raise ValueError("Critical Error: BOT_TOKEN or MONGO_URI missing in .env file.")

# Database Setup (Motor Async)
db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = db_client["insta_work_bot"]
users_col: AgnosticCollection = db["users"]

router = Router()

# ==========================================
# FAKE DATA & LOGIC
# ==========================================

# 100 Mixed Indian Names (Hindu & Muslim)
FAKE_NAMES: List[str] = [
    "Aarav Patel", "Mohammed Ali", "Vivaan Sharma", "Tariq Khan", "Aditya Singh",
    "Imran Sheikh", "Vihaan Kumar", "Zayn Malik", "Arjun Gupta", "Rehan Ansari",
    "Sai Joshi", "Yusuf Pathan", "Ayaan Desai", "Omar Farooq", "Krishna Reddy",
    "Bilal Ahmed", "Ishaan Verma", "Hamza Qureshi", "Shaurya Chauhan", "Aamir Khan",
    "Rishabh Jain", "Hassan Raza", "Kabir Das", "Zaid Syed", "Atharva Kadam",
    "Faisal Khatri", "Dhruv Menon", "Arif Hussain", "Ananya Mehra", "Fatima Bibi",
    "Riya Rajput", "Zoya Sheikh", "Aadhya Mishra", "Sana Khan", "Diya Nair",
    "Aisha Ansari", "Ishita Agarwal", "Zara Ali", "Kavya Pillai", "Maryam Siddiqui",
    "Anushka Thakur", "Alia Bhatt", "Avni Kapoor", "Mehak Mirza", "Prisha Tiwari",
    "Iqra Qazi", "Sneha Roy", "Sara Rahman", "Nandini Yadav", "Rida Hashmi",
    "Karan Malhotra", "Ravi Teja", "Sameer Verma", "Junaid Akhtar", "Deepak Chahar",
    "Sahil Baig", "Rohan Joshi", "Nadeem Saifi", "Prakash Jha", "Rizwan Beg",
    "Amitabh Bachchan", "Shoaib Malik", "Sanjay Dutt", "Usman Khawaja", "Rajesh Khanna",
    "Asad Owaisi", "Sunil Shetty", "Mustafa Zahid", "Vikram Rathore", "Tahir Raj",
    "Rahul Dravid", "Nawazuddin Siddiqui", "Anil Kapoor", "Salman Khan", "Gaurav Taneja",
    "Irfan Pathan", "Mohit Suri", "Zaheer Khan", "Harshvardhan Rane", "Danish Sait",
    "Neha Kakkar", "Farah Khan", "Pooja Hegde", "Suhana Khan", "Kriti Sanon",
    "Huma Qureshi", "Shraddha Kapoor", "Gauahar Khan", "Disha Patani", "Nushrratt Bharuccha",
    "Kiara Advani", "Tabu", "Alaya F", "Zareen Khan", "Mrunal Thakur",
    "Fatima Sana Shaikh", "Bhumi Pednekar", "Hina Khan", "Yami Gautam", "Sanjeeda Sheikh"
]

# Pre-distribute fake members across months
FAKE_MEMBERS_BY_MONTH = {
    "April 2026": FAKE_NAMES[0:25],       # 25 members
    "May 2026": FAKE_NAMES[25:47],        # 22 members
    "June 2026": FAKE_NAMES[47:68],       # 21 members
    "July 2026": FAKE_NAMES[68:89],       # 21 members
    "September 2026": FAKE_NAMES[89:100]  # 11 members
}

def get_daily_withdrawals() -> Tuple[List[Dict[str, Any]], int]:
    """Generates 15-18 random consistent withdrawals for the current day."""
    today = datetime.now().date()
    # Seed with today's date so it remains constant throughout the day but randomizes daily
    random.seed(today.toordinal())
    
    num_withdrawals = random.randint(15, 18)
    selected_names = random.sample(FAKE_NAMES, num_withdrawals)
    
    withdrawals = []
    total_amount = 0
    
    for name in selected_names:
        amount = random.randint(3, 10) * 1000  # Rs. 3000 to 10000
        hour = random.randint(9, 23)
        minute = random.randint(0, 59)
        time_str = f"{hour:02d}:{minute:02d}"
        
        withdrawals.append({
            "name": name,
            "amount": amount,
            "time": time_str
        })
        total_amount += amount
    
    # Sort by time to make it look realistic
    withdrawals.sort(key=lambda x: x["time"])
    
    # Reset random seed to system default for other random operations
    random.seed()
    
    return withdrawals, total_amount

# ==========================================
# DATABASE HELPER FUNCTIONS
# ==========================================

async def get_user(user_id: int) -> Dict[str, Any]:
    try:
        user = await users_col.find_one({"user_id": user_id})
        return user if user else {}
    except Exception as e:
        logger.error(f"Error fetching user {user_id}: {e}")
        return {}

async def register_user_if_not_exists(user_id: int, username: str, first_name: str) -> None:
    try:
        existing_user = await users_col.find_one({"user_id": user_id})
        if not existing_user:
            await users_col.insert_one({
                "user_id": user_id,
                "username": username,
                "first_name": first_name,
                "is_active": False,
                "balance": 0,
                "join_date": datetime.now()
            })
    except Exception as e:
        logger.error(f"Error registering user {user_id}: {e}")

# ==========================================
# KEYBOARDS
# ==========================================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💸 Withdrawal Done", callback_data="withdrawal_list"),
                InlineKeyboardButton(text="👥 Active Members", callback_data="active_members")
            ],
            [
                InlineKeyboardButton(text="🟢 Apply to Work", callback_data="apply_work"),
                InlineKeyboardButton(text="💰 My Balance", callback_data="my_balance")
            ],
            [
                InlineKeyboardButton(text="💳 Request Withdrawal", callback_data="request_withdraw"),
                InlineKeyboardButton(text="📝 Submit Work", callback_data="submit_work")
            ]
        ]
    )

def get_work_submission_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔗 My Instagram Links", callback_data="insta_links")],
            [InlineKeyboardButton(text="🌐 My Instagram Webs", callback_data="insta_webs")],
            [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="back_to_menu")]
        ]
    )

# ==========================================
# BOT HANDLERS
# ==========================================

@router.message(CommandStart())
async def start_cmd(message: Message) -> None:
    try:
        await register_user_if_not_exists(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.first_name or "User"
        )
        text = (
            f"Welcome {message.from_user.first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await message.answer(text, reply_markup=get_main_menu_keyboard())
    except Exception as e:
        logger.error(f"Error in start command: {e}")

@router.callback_query(F.data == "withdrawal_list")
async def show_withdrawal_list(callback: CallbackQuery) -> None:
    try:
        withdrawals, total_amount = get_daily_withdrawals()
        today_date = datetime.now().strftime("%d %B %Y")
        
        text = f"📊 **Today's Approved Withdrawals ({today_date})**\n"
        text += f"💰 **Total Amount Paid:** ₹{total_amount:,}\n\n"
        
        for w in withdrawals:
            text += f"✅ **{w['name']}** - ₹{w['amount']:,} at {w['time']}\n"
            
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in withdrawal_list: {e}")

@router.callback_query(F.data == "active_members")
async def show_active_members(callback: CallbackQuery) -> None:
    try:
        # Fetch real active members from DB (assuming they are added in September)
        real_users_cursor = users_col.find({"is_active": True})
        real_users = await real_users_cursor.to_list(length=100)
        
        text = "🌟 **Our Active Working Members** 🌟\n\n"
        
        for month, names in FAKE_MEMBERS_BY_MONTH.items():
            if month == "September 2026":
                # Combine fake sept members with real active members
                total_sept = len(names) + len(real_users)
                text += f"📅 **{month} (Total: {total_sept} Members)**\n"
                
                combined_names = names.copy()
                for u in real_users:
                    combined_names.append(u.get("first_name", "User"))
                
                text += ", ".join(combined_names) + "\n\n"
            else:
                text += f"📅 **{month} ({len(names)} Members)**\n"
                text += ", ".join(names) + "\n\n"
                
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in active_members: {e}")

@router.callback_query(F.data == "apply_work")
async def apply_for_work(callback: CallbackQuery) -> None:
    try:
        text = (
            "📝 **Apply for Work**\n\n"
            "To join our team and start running Instagram ads, please contact our Admin or wait for your account to be manually approved."
        )
        await callback.answer("Application request noted!", show_alert=False)
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in apply_work: {e}")

@router.callback_query(F.data == "my_balance")
async def show_balance(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        balance = user.get("balance", 0)
        text = (
            f"💰 **My Wallet Balance**\n\n"
            f"👤 User: {callback.from_user.first_name}\n"
            f"💵 Current Balance: ₹{balance:,}"
        )
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in my_balance: {e}")

@router.callback_query(F.data == "request_withdraw")
async def request_withdrawal(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        if not user or not user.get("is_active"):
            alert_msg = "⚠️ Access Denied!\n\nYou are not active in our working list. Please apply for work first to request a withdrawal."
            await callback.answer(alert_msg, show_alert=True)
            return
            
        balance = user.get("balance", 0)
        if balance < 3000:
            await callback.answer(f"Minimum withdrawal is ₹3000. Your balance is ₹{balance}.", show_alert=True)
        else:
            await callback.answer("Withdrawal request sent to admin for approval.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in request_withdraw: {e}")

@router.callback_query(F.data == "submit_work")
async def submit_work(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        if not user or not user.get("is_active"):
            alert_msg = "🚫 Work Access Denied!\n\nIt seems you are not working with us yet. Please apply for work to get access to the submission panel."
            await callback.answer(alert_msg, show_alert=True)
            return
            
        await callback.message.edit_text(
            "✅ **Work Submission Panel**\n\nPlease select what you want to submit:",
            reply_markup=get_work_submission_keyboard()
        )
    except Exception as e:
        logger.error(f"Error in submit_work: {e}")

@router.callback_query(F.data.in_({"insta_links", "insta_webs"}))
async def handle_insta_work(callback: CallbackQuery) -> None:
    try:
        work_type = "Instagram Links" if callback.data == "insta_links" else "Instagram Webs"
        text = f"🔗 **Submit {work_type}**\n\nPlease drop your {work_type.lower()} here in the chat."
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Back", callback_data="submit_work")]]
        ))
    except Exception as e:
        logger.error(f"Error handling insta work: {e}")

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery) -> None:
    try:
        text = (
            f"Welcome {callback.from_user.first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    except Exception as e:
        logger.error(f"Error in back_to_menu: {e}")

# ==========================================
# ADMIN COMMANDS
# ==========================================

@router.message(Command("add_user"))
async def admin_add_user(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.text.split()
        if len(args) != 2:
            await message.reply("Usage: /add_user <user_id>")
            return
            
        target_id = int(args[1])
        result = await users_col.update_one(
            {"user_id": target_id},
            {"$set": {"is_active": True}}
        )
        
        if result.modified_count > 0:
            await message.reply(f"✅ User {target_id} is now an ACTIVE member.")
        else:
            await message.reply(f"⚠️ User {target_id} not found in DB. Ask them to start the bot first.")
    except Exception as e:
        logger.error(f"Error in add_user: {e}")
        await message.reply("Error updating user. Check logs.")

@router.message(Command("add_balance"))
async def admin_add_balance(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.text.split()
        if len(args) != 3:
            await message.reply("Usage: /add_balance <user_id> <amount>")
            return
            
        target_id = int(args[1])
        amount = int(args[2])
        
        result = await users_col.update_one(
            {"user_id": target_id},
            {"$inc": {"balance": amount}}
        )
        
        if result.modified_count > 0:
            await message.reply(f"✅ Added ₹{amount} to User {target_id}'s balance.")
        else:
            await message.reply(f"⚠️ User {target_id} not found in DB.")
    except Exception as e:
        logger.error(f"Error in add_balance: {e}")
        await message.reply("Error updating balance. Check logs.")

# ==========================================
# MAIN EXECUTION
# ==========================================

async def main() -> None:
    logger.info("Starting Bot...")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"Critical error during polling: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped manually.")
