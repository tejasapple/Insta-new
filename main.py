import asyncio
import logging
import os
import random
from datetime import datetime, timedelta
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
# MULTI-ADMIN CHECK HELPER
# ==========================================

async def is_admin_user(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return True
    try:
        admin_doc = await settings_col.find_one({"_id": "admins"})
        if admin_doc and user_id in admin_doc.get("admin_list", []):
            return True
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
    return False

# ==========================================
# FAKE DATA & LOGIC
# ==========================================

FAKE_NAMES: List[str] = [
    "Rohit Verma", "Tariq Anwar", "Mohit Sharma", "Zeeshan Ali", "Shyam Tiwari", 
    "Faisal Shaikh", "Ankit Gupta", "Rizwan Ahmed", "Vikas Singh", "Adil Siddiqui", 
    "Saurabh Mishra", "Asif Ansari", "Gaurav Jain", "Kashif Baig", "Neeraj Yadav", 
    "Noman Mirza", "Manish Patel", "Rehan Qureshi", "Suresh Kumar", "Samir Malik", 
    "Ramesh Rajput", "Usman Sayyed", "Dinesh Saini", "Bilal Hashmi", "Pankaj Joshi", 
    "Haris Farooqui", "Pradeep Meena", "Junaid Mansuri", "Manoj Agarwal", "Yaseen Pathan", 
    "Nitin Bhatia", "Danish Raza", "Naveen Chawla", "Shoaib Usmani", "Praveen Dixit", 
    "Nadeem Shah", "Ashish Garg", "Altaf Hussain", "Vishal Jha", "Majid Inamdar", 
    "Sumit Khandelwal", "Sadiya Bano", "Alok Pandey", "Zainab Khatoon", "Yogesh Rathi", 
    "Lokesh Thakur", "Sandeep Bansal", "Kuldeep Chauhan", "Mandeep Dalal", "Hemant Goswami", 
    "Ravi Khatri", "Tarun Lamba", "Vinit Mathur", "Harish Saxena", "Girish Ojha", 
    "Kailash Parashar", "Prakash Rathore", "Omkar Dubey", "Shivam Tomar", "Satish Upadhyay", 
    "Dhruv Vyas", "Kamlesh Wadhwa", "Brijesh Yadav", "Jatin Arora", "Gagan Bhardwaj", 
    "Aman Chaturvedi", "Akash Kaushik", "Sagar Gautam", "Suraj Hooda", "Akhil Jaiswal", 
    "Rajat Madaan", "Rupesh Lohar", "Ram Makwana", "Mayank Negi", "Dheeraj Pal", 
    "Chirag Rawat", "Piyush Sonkar", "Tushar Tyagi", "Naman Upreti", "Chetan Vashisht", 
    "Lakshay Wadhawan", "Bhuvan Yagnik", "Payal Soni", "Ankita Mahajan", "Jagriti Pathak", 
    "Shikha Rastogi", "Megha Srivastav", "Nikita Tandon", "Swati Varshney", "Ritu Yadav"
]

FAKE_MEMBERS_BY_MONTH = {
    "April 2026": FAKE_NAMES[0:20],       
    "May 2026": FAKE_NAMES[20:40],        
    "June 2026": FAKE_NAMES[40:59],       
    "July 2026": FAKE_NAMES[59:78],       
    "September 2026": FAKE_NAMES[78:90]  
}

async def get_daily_withdrawals() -> Tuple[List[Dict[str, Any]], int, int]:
    today = datetime.now().date()
    random.seed(today.toordinal())
    
    real_users_cursor = users_col.find({"is_active": True})
    real_users = await real_users_cursor.to_list(length=1000)
    real_names = {str(u.get("first_name", "")).strip().lower() for u in real_users}
    
    available_names = [n for n in FAKE_NAMES if n.strip().lower() not in real_names]
    if len(available_names) < 20:
        available_names = FAKE_NAMES
        
    num_today = random.randint(15, 20)
    selected_today = random.sample(available_names, num_today)
    
    withdrawals_today = []
    total_today = 0
    
    for name in selected_today:
        amount = random.randint(3, 10) * 1000
        hour = random.randint(9, 23)
        minute = random.randint(0, 59)
        time_str = f"{hour:02d}:{minute:02d}"
        
        withdrawals_today.append({"name": name, "amount": amount, "time": time_str})
        total_today += amount
    
    withdrawals_today.sort(key=lambda x: x["time"])
    
    total_7days = 0
    for i in range(1, 8):
        past_date = today - timedelta(days=i)
        random.seed(past_date.toordinal())
        num_past = random.randint(15, 20)
        selected_past = random.sample(available_names, num_past)
        for _ in selected_past:
            total_7days += random.randint(3, 10) * 1000
            
    total_7days += total_today
    random.seed()
    
    return withdrawals_today, total_today, total_7days

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
        existing_by_id = await users_col.find_one({"user_id": user_id})
        if existing_by_id:
            if existing_by_id.get("first_name") == str(user_id) or not existing_by_id.get("username"):
                await users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"username": username, "first_name": first_name}}
                )
            return

        existing_by_username = None
        if username:
            existing_by_username = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
        
        if existing_by_username and existing_by_username.get("user_id") == 0:
            await users_col.update_one(
                {"_id": existing_by_username["_id"]},
                {"$set": {"user_id": user_id, "first_name": first_name}}
            )
            return

        await users_col.insert_one({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "is_active": False,
            "balance": 0,
            "submission_count": 0,
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
    waiting_for_link1 = State()
    waiting_for_link2 = State()
    waiting_for_photo = State()
    waiting_for_views = State()

class AdminStates(StatesGroup):
    waiting_for_work_link = State()
    waiting_for_proof_link = State()
    waiting_for_user_query = State()
    waiting_for_add_user = State()
    waiting_for_submission_balance = State()
    waiting_for_deny_reason = State()
    waiting_for_add_balance_amount = State()
    waiting_for_remove_balance_amount = State()
    waiting_for_update_balance_amount = State()
    waiting_for_add_admin = State()
    waiting_for_single_msg = State()
    waiting_for_broadcast_msg = State()

# ==========================================
# KEYBOARDS
# ==========================================

def get_main_menu_keyboard(work_link: str, proof_link: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    def sanitize_url(url: str) -> str:
        url = url.strip()
        if url.startswith("@"):
            return f"https://t.me/{url[1:]}"
        if not url.startswith("http://") and not url.startswith("https://"):
            return f"https://{url}"
        return url

    kb = [
        [
            InlineKeyboardButton(text="Active members", callback_data="active_members"),
            InlineKeyboardButton(text="Payout list", callback_data="withdrawal_list")
        ],
        [
            InlineKeyboardButton(text="Request withdrawal", callback_data="request_withdraw"),
            InlineKeyboardButton(text="My wallet", callback_data="my_balance")
        ],
        [
            InlineKeyboardButton(text="Apply to work", url=sanitize_url(work_link))
        ],
        [
            InlineKeyboardButton(text="Payment screenshots proof", url=sanitize_url(proof_link))
        ],
        [
            InlineKeyboardButton(text="Submit work", callback_data="submit_work")
        ]
    ]
    
    if is_admin:
        kb.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="open_admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Bot Stats", callback_data="admin_stats"),
                InlineKeyboardButton(text="➕ Add User", callback_data="admin_add_user_panel")
            ],
            [
                InlineKeyboardButton(text="🔍 Check User", callback_data="admin_check_user"),
                InlineKeyboardButton(text="📝 Pending Submissions", callback_data="admin_pending_subs")
            ],
            [
                InlineKeyboardButton(text="👥 Active Users", callback_data="admin_currently_users"),
                InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast_menu")
            ],
            [
                InlineKeyboardButton(text="👑 Manage Admins", callback_data="admin_manage_admins"),
                InlineKeyboardButton(text="🔗 Set Work Link", callback_data="admin_set_work")
            ],
            [
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
        user_id = message.from_user.id
        
        existing_by_id = await users_col.find_one({"user_id": user_id})
        is_pre_registered = False
        
        if not existing_by_id and username:
            existing_by_user = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
            if existing_by_user and existing_by_user.get("user_id") == 0:
                is_pre_registered = True

        await register_user_if_not_exists(user_id, username, first_name)
        
        if not existing_by_id and not is_pre_registered and ADMIN_ID != 0:
            notify_text = f"🆕 **New User Started the Bot!**\n\n👤 Name: {first_name}\n🔗 Username: @{username}\n🆔 ID: `{user_id}`"
            try:
                await bot.send_message(ADMIN_ID, notify_text, parse_mode="Markdown")
            except Exception:
                pass

        settings = await get_bot_settings()
        is_admin = await is_admin_user(user_id)
        
        text = (
            f"Welcome {first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await message.answer(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"], is_admin))
    except Exception as e:
        logger.error(f"Error in start command: {e}")

@router.callback_query(F.data == "withdrawal_list")
async def show_withdrawal_list(callback: CallbackQuery) -> None:
    try:
        withdrawals, total_today, total_7days = await get_daily_withdrawals()
        today_date = datetime.now().strftime("%d %B %Y")
        
        text = f"📊 **Approved Withdrawals**\n\n"
        text += f"📅 **Last 7 Days Total:** ₹{total_7days:,}\n"
        text += f"💵 **Today's Total ({today_date}):** ₹{total_today:,}\n\n"
        text += f"📜 **Today's Recent Payments:**\n"
        
        for w in withdrawals:
            text += f"✅ **{w['name']}** - ₹{w['amount']:,} at {w['time']}\n"
            
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in withdrawal_list: {e}")

@router.callback_query(F.data == "active_members")
async def show_active_members(callback: CallbackQuery) -> None:
    try:
        real_users_cursor = users_col.find({"is_active": True})
        real_users = await real_users_cursor.to_list(length=500)
        
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
            inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in active_members: {e}")

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
            inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
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
            [InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in request_withdraw: {e}")

@router.callback_query(F.data.startswith("withdraw_method_"))
async def handle_withdraw_method(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied!\n\nYou are not a verified member in our working list.", show_alert=True)
            return
            
        approval_date = user.get("approval_date")
        if not approval_date:
            approval_date = user.get("join_date")
            
        delta = datetime.now() - approval_date
        total_seconds = (timedelta(days=3) - delta).total_seconds()
        
        if total_seconds > 0:
            days_left = int(total_seconds // 86400)
            hours_left = int((total_seconds % 86400) // 3600)
            if days_left > 0:
                time_str = f"{days_left} Days left"
            else:
                time_str = f"{hours_left} Hours left"
                
            await callback.answer(f"⏳ You need to wait 3 days after joining to withdraw.\n\nTime remaining: {time_str}", show_alert=True)
            return
            
        balance = user.get("balance", 0)
        if balance < 3000:
            await callback.answer(f"Minimum withdrawal is ₹3000, you have only ₹{balance}", show_alert=True)
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
            await callback.answer("🚫 Work Access Denied!\n\nPlease wait for admin approval to submit work.", show_alert=True)
            return
            
        await state.set_state(WorkSubmission.waiting_for_link1)
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]
        ])
        
        await callback.message.edit_text(
            "📝 **Work Submission Panel**\n\nPlease send your **First Channel Link** below:",
            reply_markup=cancel_kb
        )
    except Exception as e:
        logger.error(f"Error in submit_work: {e}")

@router.message(WorkSubmission.waiting_for_link1)
async def process_work_link1(message: Message, state: FSMContext) -> None:
    try:
        await state.update_data(link1=message.text)
        await state.set_state(WorkSubmission.waiting_for_link2)
        await message.reply("✅ First link received!\n\nNow, please send your **Second Channel Link**:")
    except Exception as e:
        logger.error(f"Error in process_work_link1: {e}")

@router.message(WorkSubmission.waiting_for_link2)
async def process_work_link2(message: Message, state: FSMContext) -> None:
    try:
        await state.update_data(link2=message.text)
        await state.set_state(WorkSubmission.waiting_for_photo)
        await message.reply("✅ Second link received!\n\nNow, please send the **Channel Photo** (as a Photo).")
    except Exception as e:
        logger.error(f"Error in process_work_link2: {e}")

@router.message(WorkSubmission.waiting_for_photo, F.photo)
async def process_work_photo(message: Message, state: FSMContext) -> None:
    try:
        photo_id = message.photo[-1].file_id
        await state.update_data(photo_id=photo_id)
        await state.set_state(WorkSubmission.waiting_for_views)
        await message.reply("✅ Photo received!\n\nNow, please send the **Channels View** (e.g., 6-6 reel).")
    except Exception as e:
        logger.error(f"Error in process_work_photo: {e}")

@router.message(WorkSubmission.waiting_for_views)
async def process_work_views(message: Message, state: FSMContext) -> None:
    try:
        views = message.text
        data = await state.get_data()
        
        sub_doc = {
            "user_id": message.from_user.id,
            "user_name": message.from_user.first_name,
            "link1": data.get("link1", "N/A"),
            "link2": data.get("link2", "N/A"),
            "photo_id": data.get("photo_id"),
            "views": views,
            "status": "pending",
            "timestamp": datetime.now()
        }
        await submissions_col.insert_one(sub_doc)
        
        await users_col.update_one(
            {"user_id": message.from_user.id},
            {"$inc": {"submission_count": 1}}
        )
        
        await message.reply("🎉 **Work submitted successfully!**\nAdmin will review your work and update your payment.")
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving submission: {e}")
        await message.reply("⚠️ Failed to submit work. Please try again.")
        await state.clear()

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        settings = await get_bot_settings()
        is_admin = await is_admin_user(callback.from_user.id)
        text = (
            f"Welcome {callback.from_user.first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"], is_admin))
    except Exception as e:
        logger.error(f"Error in back_to_menu: {e}")

# ==========================================
# ADMIN PANEL (FULL CONTROL LOGIC)
# ==========================================

@router.message(Command("admin"))
async def admin_panel_cmd(message: Message, state: FSMContext) -> None:
    try:
        if not await is_admin_user(message.from_user.id):
            return
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await message.reply(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin command: {e}")

@router.callback_query(F.data == "open_admin_panel")
async def open_admin_panel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        if not await is_admin_user(callback.from_user.id):
            await callback.answer("🚫 Access Denied", show_alert=True)
            return
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await callback.message.edit_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in open_admin_panel: {e}")

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
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]]), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")

@router.callback_query(F.data == "admin_add_user_panel")
async def admin_add_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_add_user)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        text = (
            "➕ **Add / Approve User**\n\n"
            "Send the user's details to activate their account.\n"
            "Supported formats:\n"
            "• `123456789` (Telegram ID)\n"
            "• `@username` or `username`\n"
            "• `https://t.me/username`\n\n"
            "*Note: If they haven't started the bot yet, they will be pre-approved and instantly show up in Active Members!*"
        )
        await callback.message.edit_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_add_user_prompt: {e}")

@router.message(AdminStates.waiting_for_add_user)
async def admin_add_user_save(message: Message, state: FSMContext) -> None:
    try:
        query = message.text.strip()
        
        if "t.me/" in query:
            query = query.split("t.me/")[-1].strip()
        elif query.startswith("@"):
            query = query[1:].strip()
            
        is_digit = query.lstrip('-').isdigit()
        
        user = None
        if is_digit:
            user = await users_col.find_one({"user_id": int(query)})
        else:
            user = await users_col.find_one({"username": {"$regex": f"^{query}$", "$options": "i"}})
            
        if user:
            await users_col.update_one(
                {"_id": user["_id"]}, 
                {"$set": {"is_active": True, "approval_date": datetime.now()}}
            )
            name = user.get("first_name", query)
            await message.reply(f"✅ User **{name}** is now an ACTIVE member!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        else:
            user_id = int(query) if is_digit else 0
            username = query if not is_digit else ""
            name = query
            
            await users_col.insert_one({
                "user_id": user_id,
                "username": username,
                "first_name": name,
                "is_active": True,
                "approval_date": datetime.now(),
                "balance": 0,
                "submission_count": 0,
                "join_date": datetime.now()
            })
            
            success_msg = f"✅ User `{query}` has been **pre-approved** and added to Active Members!\n(Profile will fully sync when they start the bot)"
            await message.reply(success_msg, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
            
        await state.clear()
    except Exception as e:
        logger.error(f"Error in admin_add_user_save: {e}")
        await message.reply("⚠️ Error adding user. Check format.", reply_markup=get_admin_panel_keyboard())
        await state.clear()

@router.callback_query(F.data == "admin_check_user")
async def admin_check_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_user_query)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
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
        if query.lstrip('-').isdigit():
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

# --- MANAGE ADMINS LOGIC ---

@router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_admins_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_add_admin)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        text = (
            "👑 **Manage Admins**\n\n"
            "Please send the **Telegram User ID** of the person you want to make an Admin:\n\n"
            "*(This person will have full access to the admin panel)*"
        )
        await callback.message.edit_text(text, reply_markup=cancel_kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_manage_admins_prompt: {e}")

@router.message(AdminStates.waiting_for_add_admin)
async def admin_manage_admins_save(message: Message, state: FSMContext) -> None:
    try:
        new_admin_id = int(message.text.strip())
        await settings_col.update_one(
            {"_id": "admins"},
            {"$addToSet": {"admin_list": new_admin_id}},
            upsert=True
        )
        await message.reply(f"✅ User ID `{new_admin_id}` has been successfully added as an Admin!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.reply("⚠️ Please enter a valid numerical User ID.", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await message.reply("⚠️ Error adding admin. Check logs.", reply_markup=get_admin_panel_keyboard())
        await state.clear()

# --- CURRENTLY USERS LOGIC (Active Users) ---

@router.callback_query(F.data == "admin_currently_users")
async def admin_currently_users(callback: CallbackQuery) -> None:
    try:
        real_users_cursor = users_col.find({"is_active": True})
        real_users = await real_users_cursor.to_list(length=100)
        
        if not real_users:
            await callback.answer("No active assigned users found.", show_alert=True)
            return
            
        kb = InlineKeyboardBuilder()
        for u in real_users:
            name = u.get("first_name", "User")
            uid = u.get("user_id")
            kb.button(text=f"👤 {name}", callback_data=f"manage_user_{uid}")
        
        kb.button(text="« Back", callback_data="admin_cancel")
        kb.adjust(2)
        
        total_added = len(real_users)
        text = f"👥 **Currently Assigned Users**\nTotal Assigned: {total_added}\n\nSelect a user below to view their work profile and manage balance:"
        await callback.message.edit_text(text, reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_currently_users: {e}")

@router.callback_query(F.data.startswith("manage_user_"))
async def admin_manage_specific_user(callback: CallbackQuery) -> None:
    try:
        uid = int(callback.data.split("_")[-1])
        u = await users_col.find_one({"user_id": uid})
        if not u:
            await callback.answer("User not found.", show_alert=True)
            return
            
        subs_count = u.get('submission_count', 0)
        balance = u.get('balance', 0)
        
        text = (
            f"👤 **User Profile:** {u.get('first_name')}\n"
            f"🆔 **ID:** `{uid}`\n"
            f"💰 **Current Balance:** ₹{balance}\n"
            f"📥 **Total Work Submissions:** {subs_count}\n"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Add Balance", callback_data=f"addbal_{uid}"),
                InlineKeyboardButton(text="➖ Remove Balance", callback_data=f"rembal_{uid}")
            ],
            [
                InlineKeyboardButton(text="🔄 Update Balance", callback_data=f"updbal_{uid}"),
                InlineKeyboardButton(text="✉️ Send Message", callback_data=f"msguser_{uid}")
            ],
            [InlineKeyboardButton(text="« Back", callback_data="admin_currently_users")]
        ])
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in manage_user: {e}")

# --- BALANCE MANAGEMENT LOGIC ---

@router.callback_query(F.data.startswith("addbal_"))
async def prompt_add_bal(callback: CallbackQuery, state: FSMContext) -> None:
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_add_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await callback.message.edit_text("👉 Enter the numerical amount to ADD to this user's balance:", reply_markup=kb)

@router.callback_query(F.data.startswith("rembal_"))
async def prompt_rem_bal(callback: CallbackQuery, state: FSMContext) -> None:
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_remove_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await callback.message.edit_text("👉 Enter the numerical amount to REMOVE from this user's balance:", reply_markup=kb)

@router.callback_query(F.data.startswith("updbal_"))
async def prompt_upd_bal(callback: CallbackQuery, state: FSMContext) -> None:
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_update_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await callback.message.edit_text("👉 Enter the NEW exact balance amount to OVERRIDE for this user:", reply_markup=kb)

@router.message(AdminStates.waiting_for_add_balance_amount)
async def execute_add_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await users_col.update_one({"user_id": uid}, {"$inc": {"balance": amount}})
        await message.reply(f"✅ ₹{amount} added to user `{uid}`.", reply_markup=get_admin_panel_keyboard())
        
        if uid:
            try:
                await bot.send_message(uid, f"🔔 **Balance Update!**\n\n✅ ₹{amount} has been added to your wallet by the Admin.")
            except Exception as e:
                logger.error(f"Could not notify user {uid}: {e}")
                
        await state.clear()
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

@router.message(AdminStates.waiting_for_remove_balance_amount)
async def execute_rem_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await users_col.update_one({"user_id": uid}, {"$inc": {"balance": -amount}})
        await message.reply(f"✅ ₹{amount} removed from user `{uid}`.", reply_markup=get_admin_panel_keyboard())
        
        if uid:
            try:
                await bot.send_message(uid, f"🔔 **Balance Update!**\n\n⚠️ ₹{amount} has been deducted from your wallet by the Admin.")
            except Exception as e:
                logger.error(f"Could not notify user {uid}: {e}")

        await state.clear()
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

@router.message(AdminStates.waiting_for_update_balance_amount)
async def execute_upd_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await users_col.update_one({"user_id": uid}, {"$set": {"balance": amount}})
        await message.reply(f"✅ Balance of user `{uid}` updated successfully to ₹{amount}.", reply_markup=get_admin_panel_keyboard())
        
        if uid:
            try:
                await bot.send_message(uid, f"🔔 **Balance Update!**\n\n✅ Your balance has been updated to ₹{amount} by the Admin.")
            except Exception as e:
                logger.error(f"Could not notify user {uid}: {e}")
                
        await state.clear()
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

# --- SINGLE USER BROADCAST LOGIC ---

@router.callback_query(F.data.startswith("msguser_"))
async def prompt_msg_user(callback: CallbackQuery, state: FSMContext) -> None:
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_single_msg)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await callback.message.edit_text("👉 Send the message you want to send to this specific user (Text, Photo, Video, etc.):", reply_markup=kb)

@router.message(AdminStates.waiting_for_single_msg)
async def execute_msg_user(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.reply(f"✅ Message sent successfully to User ID `{uid}`!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error sending message to user: {e}")
        await message.reply("⚠️ Failed to send message. User might have blocked the bot.", reply_markup=get_admin_panel_keyboard())
        await state.clear()

# --- MULTI-SELECT BROADCAST LOGIC ---

async def get_broadcast_ui(page: int, selected_ids: list) -> InlineKeyboardMarkup:
    users = await users_col.find().sort("join_date", -1).skip(page*40).limit(40).to_list(40)
    total_users = await users_col.count_documents({})
    kb = InlineKeyboardBuilder()
    now = datetime.now()
    
    for u in users:
        uid = u["user_id"]
        name = u.get("first_name", "User")
        join_date = u.get("join_date", now)
        days_ago = (now - join_date).days
        day_str = f"{days_ago} Days ago" if days_ago > 0 else "Today"
        
        prefix = "✅" if uid in selected_ids else "📝"
        btn_text = f"{prefix} {name} - {day_str}"
        kb.button(text=btn_text, callback_data=f"bcast_tgl_{uid}_{page}")
        
    kb.adjust(1)
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"bcast_page_{page-1}"))
    if (page + 1) * 40 < total_users:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"bcast_page_{page+1}"))
    if nav_row:
        kb.row(*nav_row)
        
    kb.row(
        InlineKeyboardButton(text="📤 Send Broadcast", callback_data="bcast_send_selected"),
        InlineKeyboardButton(text="🌍 Broadcast to ALL", callback_data="bcast_send_all")
    )
    kb.row(InlineKeyboardButton(text="« Back", callback_data="open_admin_panel"))
    
    return kb.as_markup()

@router.callback_query(F.data == "admin_broadcast_menu")
async def bcast_menu_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.update_data(bcast_selected_ids=[])
        kb = await get_broadcast_ui(0, [])
        await callback.message.edit_text("📢 **Broadcast Menu**\n\nSelect users to send a message to, or broadcast to everyone:", reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error starting broadcast menu: {e}")

@router.callback_query(F.data.startswith("bcast_page_"))
async def bcast_page_change(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int(callback.data.split("_")[-1])
        data = await state.get_data()
        selected = data.get("bcast_selected_ids", [])
        kb = await get_broadcast_ui(page, selected)
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logger.error(f"Error changing broadcast page: {e}")

@router.callback_query(F.data.startswith("bcast_tgl_"))
async def bcast_toggle_user(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        parts = callback.data.split("_")
        uid = int(parts[2])
        page = int(parts[3])
        
        data = await state.get_data()
        selected = data.get("bcast_selected_ids", [])
        
        if uid in selected:
            selected.remove(uid)
        else:
            selected.append(uid)
            
        await state.update_data(bcast_selected_ids=selected)
        kb = await get_broadcast_ui(page, selected)
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception as e:
        logger.error(f"Error toggling broadcast user: {e}")

@router.callback_query(F.data.in_(["bcast_send_selected", "bcast_send_all"]))
async def bcast_prepare_send(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        mode = "all" if callback.data == "bcast_send_all" else "selected"
        data = await state.get_data()
        selected = data.get("bcast_selected_ids", [])
        
        if mode == "selected" and not selected:
            await callback.answer("⚠️ Please select at least one user first!", show_alert=True)
            return
            
        await state.set_state(AdminStates.waiting_for_broadcast_msg)
        await state.update_data(bcast_mode=mode)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_broadcast_menu")]])
        text = f"👉 Send the message you want to broadcast to **{mode.upper()}** users:\n\n*(You can send text, photo, video, etc.)*"
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error preparing broadcast message: {e}")

@router.message(AdminStates.waiting_for_broadcast_msg)
async def execute_bcast_msg(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        mode = data.get("bcast_mode")
        selected = data.get("bcast_selected_ids", [])
        
        targets = []
        if mode == "all":
            users = await users_col.find().to_list(None)
            targets = [u["user_id"] for u in users]
        else:
            targets = selected
            
        processing_msg = await message.reply(f"⏳ Broadcasting to {len(targets)} users...")
        sent_count = 0
        
        for uid in targets:
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
                sent_count += 1
                await asyncio.sleep(0.05) # Prevent flood wait
            except Exception:
                pass
                
        await processing_msg.delete()
        await message.reply(f"✅ Broadcast complete! Successfully sent to {sent_count} users.", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error sending broadcast: {e}")
        await state.clear()

# --- PENDING SUBMISSIONS LOGIC ---

@router.callback_query(F.data == "admin_pending_subs")
async def admin_show_pending_subs(callback: CallbackQuery) -> None:
    try:
        pipeline = [
            {"$match": {"status": "pending"}},
            {"$group": {
                "_id": "$user_id",
                "user_name": {"$first": "$user_name"},
                "count": {"$sum": 1}
            }}
        ]
        subs_cursor = submissions_col.aggregate(pipeline)
        grouped_subs = await subs_cursor.to_list(length=50)
        
        if not grouped_subs:
            await callback.answer("✅ No pending work submissions.", show_alert=True)
            return
            
        kb = InlineKeyboardBuilder()
        for s in grouped_subs:
            kb.button(text=f"📄 {s['user_name']} ({s['count']} pending)", callback_data=f"view_user_subs_{s['_id']}")
        
        kb.button(text="« Back", callback_data="admin_cancel")
        kb.adjust(1)
        
        await callback.message.edit_text("📋 **Pending Work Submissions:**\nClick on a user to view their grouped submissions:", reply_markup=kb.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_pending_subs: {e}")

@router.callback_query(F.data.startswith("view_user_subs_"))
async def admin_view_user_subs(callback: CallbackQuery, bot: Bot) -> None:
    try:
        user_id = int(callback.data.split("_")[-1])
        sub = await submissions_col.find_one({"user_id": user_id, "status": "pending"}, sort=[("timestamp", 1)])
        if not sub:
            await callback.answer("⚠️ No more pending submissions for this user.", show_alert=True)
            return
        
        l1 = sub.get('link1', sub.get('link', 'N/A'))
        l2 = sub.get('link2', 'N/A')
        v = sub.get('views', 'N/A')
        
        caption_text = (
            f"👤 **User:** {sub.get('user_name')}\n"
            f"🆔 **ID:** `{sub.get('user_id')}`\n"
            f"🔗 **Channel 1:** {l1}\n"
            f"🔗 **Channel 2:** {l2}\n"
            f"👁️ **Views:** {v}\n"
        )
        
        sub_id = str(sub["_id"])
        action_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Accept", callback_data=f"accept_sub_{sub_id}"),
                InlineKeyboardButton(text="❌ Deny", callback_data=f"deny_sub_{sub_id}")
            ],
            [InlineKeyboardButton(text="« Back", callback_data="admin_pending_subs")]
        ])
        
        photo_id = sub.get("photo_id")
        if photo_id:
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=photo_id,
                caption=caption_text,
                reply_markup=action_kb,
                parse_mode="Markdown"
            )
        else:
            await bot.send_message(
                chat_id=callback.from_user.id,
                text=caption_text,
                reply_markup=action_kb,
                parse_mode="Markdown"
            )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error opening user submission: {e}")

@router.callback_query(F.data.startswith("accept_sub_"))
async def admin_accept_sub(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub or sub.get("status") != "pending":
            await callback.answer("Submission already processed.", show_alert=True)
            return
            
        user_id = sub["user_id"]
        
        await state.set_state(AdminStates.waiting_for_submission_balance)
        await state.update_data(target_user_id=user_id, target_sub_id=sub_id)
        
        prompt_text = "\n\n✅ **STATUS: ACCEPTING**\n\n👉 **Please type how much balance to add for this successful task:**"
        
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + prompt_text,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=callback.message.text + prompt_text,
                reply_markup=None
            )
        await callback.answer("Enter balance to add.")
    except Exception as e:
        logger.error(f"Error in accept_sub: {e}")

@router.message(AdminStates.waiting_for_submission_balance)
async def process_submission_balance(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        if not message.text:
            await message.reply("⚠️ Please enter a valid numerical amount.")
            return
        
        amount = int(message.text.strip())
        data = await state.get_data()
        target_id = data.get("target_user_id")
        sub_id = data.get("target_sub_id")
        
        if sub_id:
            await submissions_col.update_one(
                {"_id": ObjectId(sub_id)},
                {"$set": {"status": "accepted"}}
            )
        
        if target_id:
            await users_col.update_one(
                {"user_id": target_id},
                {"$inc": {"balance": amount}}
            )
            await message.reply(f"✅ Successfully added ₹{amount} to User `{target_id}`'s balance.", parse_mode="Markdown")
            
            try:
                await bot.send_message(target_id, f"🎉 **Work Accepted!**\n\nYour recent work submission was approved.\n💰 **Balance Added:** ₹{amount}")
            except Exception as e:
                logger.error(f"Could not notify user {target_id}: {e}")
                
        await state.clear()
    except ValueError:
        await message.reply("⚠️ Please enter a valid number (e.g., 500).")
    except Exception as e:
        logger.error(f"Error adding sub balance: {e}")
        await state.clear()

@router.callback_query(F.data.startswith("deny_sub_"))
async def admin_deny_sub(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub or sub.get("status") != "pending":
            await callback.answer("Submission already processed.", show_alert=True)
            return
            
        user_id = sub["user_id"]
        
        await state.set_state(AdminStates.waiting_for_deny_reason)
        await state.update_data(target_user_id=user_id, target_sub_id=sub_id)
        
        prompt_text = "\n\n❌ **STATUS: DENYING**\n\n👉 **Please type the reason for denying this work submission:**"
        
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + prompt_text,
                reply_markup=None
            )
        else:
            await callback.message.edit_text(
                text=callback.message.text + prompt_text,
                reply_markup=None
            )
        await callback.answer("Enter denial reason.")
    except Exception as e:
        logger.error(f"Error in deny_sub: {e}")

@router.message(AdminStates.waiting_for_deny_reason)
async def process_deny_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        reason = message.text.strip()
        data = await state.get_data()
        target_id = data.get("target_user_id")
        sub_id = data.get("target_sub_id")
        
        if sub_id:
            await submissions_col.update_one(
                {"_id": ObjectId(sub_id)},
                {"$set": {"status": "denied", "deny_reason": reason}}
            )
        
        await message.reply(f"✅ Submission marked as DENIED for User `{target_id}`.", parse_mode="Markdown")
        
        if target_id:
            try:
                await bot.send_message(target_id, f"❌ **Work Denied!**\n\nYour recent work submission was declined.\n📝 **Reason:** {reason}")
            except Exception as e:
                logger.error(f"Could not notify user {target_id}: {e}")
                
        await state.clear()
    except Exception as e:
        logger.error(f"Error denying sub: {e}")
        await state.clear()

# --- OTHER ADMIN PANEL COMMANDS ---

@router.callback_query(F.data == "admin_set_work")
async def admin_set_work_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_work_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        await callback.message.edit_text("🔗 **Set Work Link**\n\nPlease send the new URL for the 'Apply to Work' button:", reply_markup=cancel_kb, parse_mode="Markdown")
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
        await message.reply(f"✅ 'Apply to Work' button link updated successfully!\n\nNew Link: {new_link}", reply_markup=get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error saving work link: {e}")

@router.callback_query(F.data == "admin_set_proof")
async def admin_set_proof_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_proof_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
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
# OLD ADMIN COMMANDS
# ==========================================

@router.message(Command("add_user"))
async def admin_add_user(message: Message) -> None:
    try:
        if not await is_admin_user(message.from_user.id):
            return
            
        args = message.text.split(maxsplit=1)
        if len(args) != 2:
            await message.reply("Usage: `/add_user <user_id | @username | t.me/link | First Name>`\n\n*Tip: You can now use the Admin Panel to do this easily!*", parse_mode="Markdown")
            return
            
        query = args[1].strip()
        
        if "t.me/" in query:
            query = query.split("t.me/")[-1]
        elif query.startswith("@"):
            query = query[1:]
            
        db_query = {}
        if query.lstrip('-').isdigit():
            db_query = {"user_id": int(query)}
        else:
            db_query = {"$or": [
                {"username": {"$regex": f"^{query}$", "$options": "i"}},
                {"first_name": {"$regex": f"^{query}$", "$options": "i"}}
            ]}
            
        users = await users_col.find(db_query).to_list(5)
        
        if not users:
            await message.reply(f"⚠️ No matching user found for `{query}`. You can add them through the Admin Panel to pre-approve them.", parse_mode="Markdown")
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
async def admin_add_balance(message: Message, bot: Bot) -> None:
    try:
        if not await is_admin_user(message.from_user.id):
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
            try:
                await bot.send_message(target_id, f"🔔 **Balance Update!**\n\n✅ ₹{amount} has been added to your wallet by the Admin.")
            except Exception:
                pass
        else:
            await message.reply(f"⚠️ User `{target_id}` not found in DB.", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in add_balance: {e}")
        await message.reply("Error updating balance. Check logs.")

@router.message(Command("set_work_link"))
async def admin_set_work_link(message: Message) -> None:
    try:
        if not await is_admin_user(message.from_user.id):
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
        await message.reply(f"✅ 'Apply to Work' button link updated to: {new_link}")
    except Exception as e:
        logger.error(f"Error setting work link: {e}")

@router.message(Command("set_proof_link"))
async def admin_set_proof_link(message: Message) -> None:
    try:
        if not await is_admin_user(message.from_user.id):
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
        if not await is_admin_user(message.from_user.id):
            return
            
        pipeline = [
            {"$match": {"status": "pending"}},
            {"$group": {
                "_id": "$user_id",
                "user_name": {"$first": "$user_name"},
                "count": {"$sum": 1}
            }}
        ]
        subs_cursor = submissions_col.aggregate(pipeline)
        grouped_subs = await subs_cursor.to_list(length=50)
        
        if not grouped_subs:
            await message.reply("✅ No pending work submissions.")
            return
            
        kb = InlineKeyboardBuilder()
        for s in grouped_subs:
            kb.button(text=f"📄 {s['user_name']} ({s['count']} pending)", callback_data=f"view_user_subs_{s['_id']}")
        
        kb.adjust(1)
        await message.reply("📋 **Pending Work Submissions:**\nClick on a user to view their submissions:", reply_markup=kb.as_markup())
        
    except Exception as e:
        logger.error(f"Error loading submissions: {e}")

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
