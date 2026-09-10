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
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import motor.motor_asyncio
from motor.core import AgnosticCollection
from bson import ObjectId

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
submissions_col: AgnosticCollection = db["submissions"]
settings_col: AgnosticCollection = db["settings"]

router = Router()

# ==========================================
# FAKE DATA & LOGIC (Untouched as requested)
# ==========================================

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

FAKE_MEMBERS_BY_MONTH = {
    "April 2026": FAKE_NAMES[0:25],       
    "May 2026": FAKE_NAMES[25:47],        
    "June 2026": FAKE_NAMES[47:68],       
    "July 2026": FAKE_NAMES[68:89],       
    "September 2026": FAKE_NAMES[89:100]  
}

def get_daily_withdrawals() -> Tuple[List[Dict[str, Any]], int]:
    today = datetime.now().date()
    random.seed(today.toordinal())
    
    num_withdrawals = random.randint(15, 18)
    selected_names = random.sample(FAKE_NAMES, num_withdrawals)
    
    withdrawals = []
    total_amount = 0
    
    for name in selected_names:
        amount = random.randint(3, 10) * 1000
        hour = random.randint(9, 23)
        minute = random.randint(0, 59)
        time_str = f"{hour:02d}:{minute:02d}"
        
        withdrawals.append({"name": name, "amount": amount, "time": time_str})
        total_amount += amount
    
    withdrawals.sort(key=lambda x: x["time"])
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
                "submission_count": 0,  # Added to track user usage
                "join_date": datetime.now(),
                "approval_date": None
            })
    except Exception as e:
        logger.error(f"Error registering user {user_id}: {e}")

async def get_bot_settings() -> Dict[str, str]:
    try:
        settings = await settings_col.find_one({"_id": "global_links"})
        if not settings:
            return {
                "work_link": "https://instagram.com", 
                "proof_link": "https://t.me"
            }
        return settings
    except Exception as e:
        logger.error(f"Error fetching settings: {e}")
        return {"work_link": "https://instagram.com", "proof_link": "https://t.me"}

# ==========================================
# FSM STATES
# ==========================================

class WorkSubmission(StatesGroup):
    waiting_for_link = State()
    waiting_for_photo = State()

class AdminStates(StatesGroup):
    waiting_for_work_link = State()
    waiting_for_proof_link = State()
    waiting_for_user_query = State()

# ==========================================
# KEYBOARDS
# ==========================================

def get_main_menu_keyboard(work_link: str, proof_link: str) -> InlineKeyboardMarkup:
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
            ],
            [
                InlineKeyboardButton(text="🚀 Start Work Now", url=work_link)
            ],
            [
                InlineKeyboardButton(text="🧾 Payment Screenshot Proof", url=proof_link)
            ]
        ]
    )

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Bot Stats", callback_data="admin_stats"),
                InlineKeyboardButton(text="🔍 Check User", callback_data="admin_check_user")
            ],
            [
                InlineKeyboardButton(text="📝 Pending Submissions", callback_data="admin_pending_subs")
            ],
            [
                InlineKeyboardButton(text="🔗 Set Work Link", callback_data="admin_set_work"),
                InlineKeyboardButton(text="🔗 Set Proof Link", callback_data="admin_set_proof")
            ],
            [
                InlineKeyboardButton(text="❌ Close Panel", callback_data="admin_close")
            ]
        ]
    )

# ==========================================
# BOT HANDLERS
# ==========================================

@router.message(CommandStart())
async def start_cmd(message: Message, bot: Bot, state: FSMContext) -> None:
    try:
        await state.clear()
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or "User"
        
        # Register user
        existing_user = await users_col.find_one({"user_id": message.from_user.id})
        await register_user_if_not_exists(message.from_user.id, username, first_name)
        
        # Notify admin for new users
        if not existing_user and ADMIN_ID != 0:
            notify_text = f"🆕 **New User Started the Bot!**\n\n👤 Name: {first_name}\n🔗 Username: @{username}\n🆔 ID: `{message.from_user.id}`"
            await bot.send_message(ADMIN_ID, notify_text, parse_mode="Markdown")

        settings = await get_bot_settings()
        text = (
            f"Welcome {first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await message.answer(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"]))
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
        real_users_cursor = users_col.find({"is_active": True})
        real_users = await real_users_cursor.to_list(length=100)
        
        text = "🌟 **Our Active Working Members** 🌟\n\n"
        
        for month, names in FAKE_MEMBERS_BY_MONTH.items():
            if month == "September 2026":
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

# ==========================================
# WITHDRAWAL FLOW
# ==========================================

@router.callback_query(F.data == "request_withdraw")
async def request_withdrawal(callback: CallbackQuery) -> None:
    try:
        text = (
            "💵 **Exchange Rate: $1 = ₹93 INR**\n\n"
            "Please select your preferred withdrawal method below:"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🏦 UPI", callback_data="withdraw_method_upi"),
                InlineKeyboardButton(text="🪙 Crypto", callback_data="withdraw_method_crypto")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in request_withdraw: {e}")

@router.callback_query(F.data.startswith("withdraw_method_"))
async def handle_withdraw_method(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        
        # 1. Normal user logic (Access Denied)
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied!\n\nYou are not a verified member in our working list.", show_alert=True)
            return
            
        # 2. Approved member logic
        approval_date = user.get("approval_date")
        if not approval_date:
            approval_date = user.get("join_date")
            
        delta = datetime.now() - approval_date
        
        # 3 Days Limit
        if delta.days < 3:
            await callback.answer(f"⏳ You need to wait 3 days after joining to withdraw.\n\nYour account has been active for {delta.days} day(s).", show_alert=True)
            return
            
        # 3000 Minimum Limit
        balance = user.get("balance", 0)
        if balance < 3000:
            await callback.answer(f"❌ Minimum withdrawal is ₹3000.\n\nYour current balance is ₹{balance}.", show_alert=True)
            return
            
        method = callback.data.split("_")[-1].upper()
        await callback.answer(f"✅ Your {method} withdrawal request is eligible! Please contact Admin.", show_alert=True)
        
    except Exception as e:
        logger.error(f"Error in withdraw method processing: {e}")

# ==========================================
# WORK SUBMISSION FLOW (FSM)
# ==========================================

@router.callback_query(F.data == "submit_work")
async def submit_work_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        user = await get_user(callback.from_user.id)
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Work Access Denied!\n\nPlease apply for work first to submit proofs.", show_alert=True)
            return
            
        await state.set_state(WorkSubmission.waiting_for_link)
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Submission", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(
            "📝 **Work Submission Panel**\n\nPlease send your **Instagram Link** below:",
            reply_markup=cancel_kb
        )
    except Exception as e:
        logger.error(f"Error in submit_work: {e}")

@router.message(WorkSubmission.waiting_for_link)
async def process_work_link(message: Message, state: FSMContext) -> None:
    try:
        await state.update_data(link=message.text)
        await state.set_state(WorkSubmission.waiting_for_photo)
        await message.reply("✅ Link received!\n\nNow, please send the **Screenshot Proof** (as a Photo).")
    except Exception as e:
        logger.error(f"Error in process_work_link: {e}")

@router.message(WorkSubmission.waiting_for_photo, F.photo)
async def process_work_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        link = data.get("link", "No Link")
        photo_id = message.photo[-1].file_id
        
        # Save submission to Database
        sub_doc = {
            "user_id": message.from_user.id,
            "user_name": message.from_user.first_name,
            "link": link,
            "photo_id": photo_id,
            "status": "pending",
            "timestamp": datetime.now()
        }
        await submissions_col.insert_one(sub_doc)
        
        # Track User Usage / Update Submission Count
        await users_col.update_one(
            {"user_id": message.from_user.id},
            {"$inc": {"submission_count": 1}}
        )
        
        await message.reply("🎉 **Work submitted successfully!**\nAdmin will review your work and update your payment manually.")
        await state.clear()
        
        # Notify Admin
        if ADMIN_ID != 0:
            await bot.send_message(
                ADMIN_ID,
                f"📥 **New Work Submission!**\n👤 By: {message.from_user.first_name}\n\nUse Admin Panel or `/submissions` to review it."
            )
    except Exception as e:
        logger.error(f"Error saving submission: {e}")
        await message.reply("⚠️ Failed to submit work. Please try again.")
        await state.clear()

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        settings = await get_bot_settings()
        text = (
            f"Welcome {callback.from_user.first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"]))
    except Exception as e:
        logger.error(f"Error in back_to_menu: {e}")

# ==========================================
# ADMIN PANEL (NEW FULL CONTROL LOGIC)
# ==========================================

@router.message(Command("admin"))
async def admin_panel_cmd(message: Message, state: FSMContext) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await message.reply(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin command: {e}")

@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery) -> None:
    try:
        total_users = await users_col.count_documents({})
        active_users = await users_col.count_documents({"is_active": True})
        total_subs = await submissions_col.count_documents({})
        pending_subs = await submissions_col.count_documents({"status": "pending"})
        
        text = (
            "📊 **Bot Statistics**\n\n"
            f"👥 **Total Users:** {total_users}\n"
            f"✅ **Active Members:** {active_users}\n"
            f"📥 **Total Submissions:** {total_subs}\n"
            f"⏳ **Pending Submissions:** {pending_subs}"
        )
        await callback.message.edit_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")

@router.callback_query(F.data == "admin_check_user")
async def admin_check_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_user_query)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")]])
        await callback.message.edit_text("🔍 **Check User**\n\nPlease send the User ID, @username, or First Name of the user:", reply_markup=cancel_kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_check_user_prompt: {e}")

@router.message(AdminStates.waiting_for_user_query)
async def admin_check_user_result(message: Message, state: FSMContext) -> None:
    try:
        query = message.text.strip()
        if query.startswith("@"):
            query = query[1:]
            
        db_query = {}
        if query.isdigit():
            db_query = {"user_id": int(query)}
        else:
            db_query = {"$or": [
                {"username": {"$regex": f"^{query}$", "$options": "i"}},
                {"first_name": {"$regex": f"^{query}$", "$options": "i"}}
            ]}
            
        users = await users_col.find(db_query).to_list(5)
        
        if not users:
            await message.reply(f"⚠️ No user found for `{query}`.", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
            await state.clear()
            return
            
        for u in users:
            join_date = u.get("join_date", datetime.now()).strftime("%Y-%m-%d")
            status = "✅ Active" if u.get("is_active") else "🚫 Inactive"
            text = (
                f"👤 **User Info:**\n\n"
                f"**Name:** {u.get('first_name')}\n"
                f"**Username:** @{u.get('username', 'N/A')}\n"
                f"**ID:** `{u.get('user_id')}`\n"
                f"**Status:** {status}\n"
                f"**Balance:** ₹{u.get('balance', 0)}\n"
                f"**Total Submissions:** {u.get('submission_count', 0)}\n"
                f"**Joined:** {join_date}"
            )
            await message.reply(text, parse_mode="Markdown")
            
        await message.answer("Select another action:", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error in admin_check_user_result: {e}")

@router.callback_query(F.data == "admin_pending_subs")
async def admin_show_pending_subs(callback: CallbackQuery) -> None:
    try:
        subs = await submissions_col.find({"status": "pending"}).to_list(50)
        if not subs:
            await callback.answer("✅ No pending work submissions.", show_alert=True)
            return
            
        kb = InlineKeyboardBuilder()
        for s in subs:
            kb.button(text=f"📄 {s.get('user_name', 'User')}", callback_data=f"view_sub_{str(s['_id'])}")
        
        kb.button(text="🔙 Back to Panel", callback_data="admin_cancel")
        kb.adjust(1)
        
        await callback.message.edit_text("📋 **Pending Work Submissions:**\nClick on a name to view their submitted link and screenshot:", reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_pending_subs: {e}")

@router.callback_query(F.data == "admin_set_work")
async def admin_set_work_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_work_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")]])
        await callback.message.edit_text("🔗 **Set Work Link**\n\nPlease send the new URL for the 'Start Work Now' button:", reply_markup=cancel_kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_set_work_prompt: {e}")

@router.message(AdminStates.waiting_for_work_link)
async def admin_set_work_save(message: Message, state: FSMContext) -> None:
    try:
        new_link = message.text.strip()
        await settings_col.update_one(
            {"_id": "global_links"},
            {"$set": {"work_link": new_link}},
            upsert=True
        )
        await message.reply(f"✅ 'Start Work Now' button link updated successfully!\n\nNew Link: {new_link}", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving work link: {e}")

@router.callback_query(F.data == "admin_set_proof")
async def admin_set_proof_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_proof_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")]])
        await callback.message.edit_text("🔗 **Set Proof Link**\n\nPlease send the new URL for the 'Payment Screenshot Proof' button:", reply_markup=cancel_kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_set_proof_prompt: {e}")

@router.message(AdminStates.waiting_for_proof_link)
async def admin_set_proof_save(message: Message, state: FSMContext) -> None:
    try:
        new_link = message.text.strip()
        await settings_col.update_one(
            {"_id": "global_links"},
            {"$set": {"proof_link": new_link}},
            upsert=True
        )
        await message.reply(f"✅ 'Payment Screenshot Proof' button link updated successfully!\n\nNew Link: {new_link}", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving proof link: {e}")

@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_action(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await callback.message.edit_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_cancel: {e}")

@router.callback_query(F.data == "admin_close")
async def admin_close_panel(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Error closing admin panel: {e}")

# ==========================================
# OLD ADMIN COMMANDS (Preserved as requested)
# ==========================================

@router.message(Command("add_user"))
async def admin_add_user(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
            
        args = message.text.split(maxsplit=1)
        if len(args) != 2:
            await message.reply("Usage: `/add_user <user_id | @username | t.me/link | First Name>`", parse_mode="Markdown")
            return
            
        query = args[1].strip()
        
        # Clean query if it's a link or @
        if "t.me/" in query:
            query = query.split("t.me/")[-1]
        elif query.startswith("@"):
            query = query[1:]
            
        db_query = {}
        if query.isdigit():
            db_query = {"user_id": int(query)}
        else:
            db_query = {"$or": [
                {"username": {"$regex": f"^{query}$", "$options": "i"}},
                {"first_name": {"$regex": f"^{query}$", "$options": "i"}}
            ]}
            
        users = await users_col.find(db_query).to_list(5)
        
        if not users:
            await message.reply(f"⚠️ No matching user found for `{query}`. Ask them to start the bot first.", parse_mode="Markdown")
            return
            
        if len(users) > 1:
            names = [f"• {u.get('first_name')} (ID: `{u.get('user_id')}`)" for u in users]
            await message.reply("⚠️ Multiple users found. Please use exact ID:\n" + "\n".join(names), parse_mode="Markdown")
            return
            
        target_id = users[0]["user_id"]
        result = await users_col.update_one(
            {"user_id": target_id},
            {"$set": {"is_active": True, "approval_date": datetime.now()}}
        )
        
        if result.modified_count > 0:
            await message.reply(f"✅ User **{users[0].get('first_name')}** (`{target_id}`) is now an ACTIVE member.", parse_mode="Markdown")
        else:
            await message.reply("User is already active.")
            
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
            await message.reply("Usage: `/add_balance <user_id> <amount>`", parse_mode="Markdown")
            return
            
        target_id = int(args[1])
        amount = int(args[2])
        
        result = await users_col.update_one(
            {"user_id": target_id},
            {"$inc": {"balance": amount}}
        )
        
        if result.modified_count > 0:
            await message.reply(f"✅ Successfully added ₹{amount} to User `{target_id}`'s balance. (Manual Update)", parse_mode="Markdown")
        else:
            await message.reply(f"⚠️ User `{target_id}` not found in DB.", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in add_balance: {e}")
        await message.reply("Error updating balance. Check logs.")

@router.message(Command("set_work_link"))
async def admin_set_work_link(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
        args = message.text.split(maxsplit=1)
        if len(args) != 2:
            return await message.reply("Usage: `/set_work_link <https://...>`", parse_mode="Markdown")
            
        new_link = args[1].strip()
        await settings_col.update_one(
            {"_id": "global_links"},
            {"$set": {"work_link": new_link}},
            upsert=True
        )
        await message.reply(f"✅ 'Start Work Now' button link updated to: {new_link}")
    except Exception as e:
        logger.error(f"Error setting work link: {e}")

@router.message(Command("set_proof_link"))
async def admin_set_proof_link(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
        args = message.text.split(maxsplit=1)
        if len(args) != 2:
            return await message.reply("Usage: `/set_proof_link <https://...>`", parse_mode="Markdown")
            
        new_link = args[1].strip()
        await settings_col.update_one(
            {"_id": "global_links"},
            {"$set": {"proof_link": new_link}},
            upsert=True
        )
        await message.reply(f"✅ 'Payment Screenshot Proof' button link updated to: {new_link}")
    except Exception as e:
        logger.error(f"Error setting proof link: {e}")

@router.message(Command("submissions"))
async def admin_view_submissions(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
            return
            
        subs = await submissions_col.find({"status": "pending"}).to_list(50)
        if not subs:
            await message.reply("✅ No pending work submissions.")
            return
            
        kb = InlineKeyboardBuilder()
        for s in subs:
            # Inline button with User's Name
            kb.button(text=f"📄 {s.get('user_name', 'User')}", callback_data=f"view_sub_{str(s['_id'])}")
        
        kb.adjust(1)
        await message.reply("📋 **Pending Work Submissions:**\nClick on a name to view their submitted link and screenshot:", reply_markup=kb.as_markup())
        
    except Exception as e:
        logger.error(f"Error loading submissions: {e}")

@router.callback_query(F.data.startswith("view_sub_"))
async def admin_open_submission(callback: CallbackQuery, bot: Bot) -> None:
    try:
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub:
            await callback.answer("⚠️ Submission not found or already processed.", show_alert=True)
            return
            
        caption_text = (
            f"👤 **User:** {sub.get('user_name')}\n"
            f"🆔 **ID:** `{sub.get('user_id')}`\n"
            f"🔗 **Link:** {sub.get('link')}\n\n"
            "Use `/add_balance` to manually update their payment."
        )
        
        action_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Mark as Checked (Clear)", callback_data=f"clear_sub_{sub_id}")]
        ])
        
        # Send Photo with the Link in Caption
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=sub.get("photo_id"),
            caption=caption_text,
            reply_markup=action_kb,
            parse_mode="Markdown"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error opening submission: {e}")

@router.callback_query(F.data.startswith("clear_sub_"))
async def admin_clear_submission(callback: CallbackQuery) -> None:
    try:
        sub_id = callback.data.split("_")[-1]
        await submissions_col.update_one(
            {"_id": ObjectId(sub_id)},
            {"$set": {"status": "checked"}}
        )
        await callback.message.edit_caption(
            caption=callback.message.caption + "\n\n✅ **STATUS: CHECKED & CLEARED**",
            reply_markup=None
        )
        await callback.answer("Submission cleared!")
    except Exception as e:
        logger.error(f"Error clearing submission: {e}")

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
