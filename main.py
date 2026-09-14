import asyncio
import logging
import os
import random
import re
import json
from datetime import datetime, timedelta, time
from typing import Any, Dict, List, Tuple, Callable, Awaitable, Optional

from aiogram import Bot, Dispatcher, Router, F, BaseMiddleware
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LinkPreviewOptions,
    TelegramObject,
    BufferedInputFile,
    MessageOriginUser
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from dotenv import load_dotenv
import motor.motor_asyncio
from motor.core import AgnosticCollection
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
dp_texts_col: AgnosticCollection = db["dp_texts"] 
help_queries_col: AgnosticCollection = db["help_queries"]

# ==========================================
# MONGODB MEDIA STORAGE 
# ==========================================

async def load_media() -> Dict[str, Any]:
    default_data = {
        "dp_storage": {"step1": [], "step2": [], "step3": [], "step4": []},
        "dp_bank": []
    }
    try:
        doc = await settings_col.find_one({"_id": "media_storage"})
        if doc and "data" in doc:
            return doc["data"]
        return default_data
    except Exception as e:
        logger.error(f"Error loading media from DB, returning default: {e}")
        return default_data

async def save_media(data: Dict[str, Any]) -> None:
    try:
        await settings_col.update_one(
            {"_id": "media_storage"},
            {"$set": {"data": data}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving media to DB: {e}")

# ==========================================
# HELPER FUNCTIONS (INCLUDES BACK BUTTON FIX)
# ==========================================

def clean_md(text: Any) -> str:
    """Sanitize user input to prevent Telegram Markdown parsing errors."""
    if text is None: return "N/A"
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('[', '\\[').replace(']', '\\]').replace('`', '\\`')

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

def parse_telegram_link(link: str) -> Tuple[Optional[Any], Optional[Any]]:
    match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)', link)
    if match:
        chat_ref = match.group(1)
        msg_id = int(match.group(2))
        if chat_ref.isdigit():
            chat_id = int("-100" + chat_ref)
        else:
            chat_id = "@" + chat_ref
        return chat_id, msg_id
    return None, None

async def safe_edit_message(callback: CallbackQuery, text: str, reply_markup: Optional[InlineKeyboardMarkup] = None, parse_mode: str = "Markdown") -> None:
    """Fixes the Back Button bug by safely handling transitions from Photo to Text messages."""
    try:
        if callback.message.photo or callback.message.video or callback.message.document:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Safe edit failed: {e}")

# ==========================================
# MAINTENANCE & BAN MIDDLEWARE
# ==========================================
class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self, 
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]], 
        event: TelegramObject, 
        data: Dict[str, Any]
    ) -> Any:
        user = data.get("event_from_user")
        if user:
            try:
                # Check if user is permanently banned
                user_doc = await users_col.find_one({"user_id": user.id})
                if user_doc and user_doc.get("is_banned", False):
                    if isinstance(event, Message):
                        await event.answer("🚫 **Access Denied**\n\nYou have been permanently banned from using this bot.", parse_mode="Markdown")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("🚫 You are permanently banned.", show_alert=True)
                    return

                status_doc = await settings_col.find_one({"_id": "system_status"})
                is_maintenance = status_doc.get("maintenance_mode", False) if status_doc else False
                
                if is_maintenance:
                    is_admin = await is_admin_user(user.id)
                    if not is_admin:
                        if isinstance(event, Message):
                            await event.answer("🛠 **Maintenance Mode ON**\n\nThe bot is currently undergoing maintenance and upgrades. Please check back later!", parse_mode="Markdown")
                        elif isinstance(event, CallbackQuery):
                            await event.answer("🛠 Maintenance Mode ON. The bot is being upgraded.", show_alert=True)
                        return 
            except Exception as e:
                logger.error(f"Middleware Error: {e}")
        
        return await handler(event, data)

router = Router()
router.message.middleware(MaintenanceMiddleware())
router.callback_query.middleware(MaintenanceMiddleware())

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
    today = datetime.now()
    today_date = today.date()
    random.seed(today_date.toordinal())
    
    # 100% Ensure NO Real Users ever go in payout list
    real_users_cursor = users_col.find({"is_active": True})
    real_users = await real_users_cursor.to_list(length=5000)
    real_names = {str(u.get("first_name", "")).strip().lower() for u in real_users}
    
    available_names = [n for n in FAKE_NAMES if n.strip().lower() not in real_names]
    
    # Strictly bound to 12-15 fake names
    num_today = random.randint(12, 15)
    selected_today = random.sample(available_names, min(num_today, len(available_names)))
    
    # Ensure 2-3 members for crypto and 2-3 for 00 amounts
    crypto_indices = random.sample(range(num_today), min(random.randint(2, 3), num_today))
    zero_indices = random.sample(range(num_today), min(random.randint(2, 3), num_today))
    
    # Spread evenly across the entire 24 hour day (0 to 23) to ensure morning updates
    times = []
    for _ in range(num_today):
        times.append(time(random.randint(0, 23), random.randint(0, 59)))
    times.sort()
    
    all_today_withdrawals = []
    for i in range(num_today):
        name = selected_today[i]
        w_time = times[i]
        
        is_crypto = i in crypto_indices
        is_zeros = i in zero_indices
        
        # FEATURE 2: FAKE EMP ID & UTR / TXN HASH GENERATION
        emp_id = f"EMP-{random.randint(10000, 99999)}"
        
        if is_crypto:
            amount = random.randint(30, 85)
            amount_str = f"{amount} Crypto"
            raw_amount = 0
            txn_hash = f"0x{random.randint(10000000, 99999999):x}{random.randint(1000, 9999):x}"
            utr = None
        else:
            amount = random.randint(3000, 8000)
            if is_zeros:
                amount = (amount // 100) * 100 # Makes sure it ends in 00
            amount_str = f"₹{amount}"
            raw_amount = amount
            txn_hash = None
            utr = f"329{random.randint(100000000, 999999999)}"
            
        all_today_withdrawals.append({
            "name": name,
            "emp_id": emp_id,
            "amount_str": amount_str,
            "raw_amount": raw_amount,
            "time": w_time.strftime("%H:%M"),
            "time_obj": w_time,
            "is_crypto": is_crypto,
            "txn_hash": txn_hash,
            "utr": utr
        })
    
    # Filter for what should be visible at this exact moment in the day
    current_time = today.time()
    withdrawals_today = [w for w in all_today_withdrawals if w["time_obj"] <= current_time]
    
    total_today_inr = sum(w["raw_amount"] for w in withdrawals_today if not w["is_crypto"])
    
    total_7days_inr = 0
    for i in range(1, 8):
        past_date = today_date - timedelta(days=i)
        random.seed(past_date.toordinal())
        num_past = random.randint(12, 15)
        for j in range(num_past):
            amount = random.randint(3000, 8000)
            total_7days_inr += amount
            
    total_7days_inr += total_today_inr
    random.seed() # reset random state
    
    return withdrawals_today, total_today_inr, total_7days_inr

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
            update_fields = {}
            if existing_by_id.get("first_name") == str(user_id) or not existing_by_id.get("username"):
                update_fields["username"] = username
                update_fields["first_name"] = first_name
            # Ensure everyone gets an employee ID eventually
            if not existing_by_id.get("emp_id"):
                update_fields["emp_id"] = f"EMP-{random.randint(10000, 99999)}"
            if "tc_accepted" not in existing_by_id:
                update_fields["tc_accepted"] = False
                
            if update_fields:
                await users_col.update_one({"user_id": user_id}, {"$set": update_fields})
            return

        existing_by_username = None
        if username:
            existing_by_username = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
        
        if existing_by_username and existing_by_username.get("user_id") == 0:
            await users_col.update_one(
                {"_id": existing_by_username["_id"]},
                {"$set": {
                    "user_id": user_id, 
                    "first_name": first_name,
                    "emp_id": f"EMP-{random.randint(10000, 99999)}",
                    "tc_accepted": False
                }}
            )
            return

        await users_col.insert_one({
            "user_id": user_id,
            "username": username,
            "first_name": first_name,
            "is_active": False,
            "is_banned": False,
            "emp_id": f"EMP-{random.randint(10000, 99999)}",
            "tc_accepted": False,
            "balance": 0,
            "submission_count": 0,
            "join_date": datetime.now(),
            "approval_date": None,
            "schedule_step": 0,
            "sent_batches": [],
            "pending_second_batch": False, 
            "work_approved": True, 
            "last_work_time": None,
            "notified_new_work": False, 
            "has_submitted_current_work": True,
            "notified_missed_4h": False,
            "notified_missed_6h": False,
            "notified_missed_8h": False
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
    dashboard = State()
    waiting_for_link1 = State()
    waiting_for_link2 = State()
    waiting_for_photo1 = State()
    waiting_for_photo2 = State()

class WithdrawStates(StatesGroup):
    waiting_for_upi = State()
    waiting_for_crypto = State()

class StaffHelpStates(StatesGroup):
    waiting_for_message = State()

class AdminStates(StatesGroup):
    waiting_for_work_link = State()
    waiting_for_proof_link = State()
    waiting_for_user_query = State()
    waiting_for_add_user = State()
    waiting_for_submission_balance = State()
    waiting_for_all_submission_balance = State() 
    waiting_for_deny_reason = State()
    waiting_for_add_balance_amount = State()
    waiting_for_remove_balance_amount = State()
    waiting_for_update_balance_amount = State()
    waiting_for_add_admin = State()
    waiting_for_single_msg = State()
    waiting_for_broadcast_msg = State()
    waiting_for_dump_channel_link = State() 
    waiting_for_dump_total_videos = State()
    waiting_for_dp_storage_media = State()
    waiting_for_dp_bank_media = State()
    waiting_for_help_reply = State()
    waiting_for_notice = State() # NEW FEATURE: Notice Board State

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
            InlineKeyboardButton(text="👥 Active members", callback_data="active_members"),
            InlineKeyboardButton(text="📜 Payout list", callback_data="withdrawal_list")
        ],
        [
            InlineKeyboardButton(text="💸 Request withdrawal", callback_data="request_withdraw"),
            InlineKeyboardButton(text="💰 My wallet", callback_data="my_balance")
        ],
        [
            InlineKeyboardButton(text="👨‍💼 Staff Only", callback_data="staff_only_menu") 
        ],
        [
            InlineKeyboardButton(text="❓ FAQ", callback_data="staff_faq") 
        ],
        [
            InlineKeyboardButton(text="💼 Apply to work", url=sanitize_url(work_link))
        ],
        [
            InlineKeyboardButton(text="📢 Updates", url=sanitize_url(proof_link))
        ]
    ]
    
    if is_admin:
        kb.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="open_admin_panel")])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def get_admin_panel_keyboard() -> InlineKeyboardMarkup:
    status_doc = await settings_col.find_one({"_id": "system_status"})
    maintenance_on = status_doc.get("maintenance_mode", False) if status_doc else False
    maintenance_text = "🛠 Maint: ON 🟢" if maintenance_on else "🛠 Maint: OFF 🔴"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Bot Stats", callback_data="admin_stats"),
                InlineKeyboardButton(text="➕ Add User", callback_data="admin_add_user_panel")
            ],
            [
                InlineKeyboardButton(text="🖼️ DP Storage", callback_data="admin_dp_storage_menu"),
                InlineKeyboardButton(text="🏦 DP Bank", callback_data="admin_dp_bank_menu") 
            ],
            [
                InlineKeyboardButton(text="🔍 Check User", callback_data="admin_check_user"),
                InlineKeyboardButton(text="📥 Set Dump", callback_data="admin_set_dump_channel") 
            ],
            [
                InlineKeyboardButton(text="📝 Unmarked Subs", callback_data="admin_unmarked_subs_0"), 
                InlineKeyboardButton(text="✅ Marked Subs", callback_data="admin_marked_subs_0") 
            ],
            [
                InlineKeyboardButton(text="👥 Active Users", callback_data="admin_currently_users_0"),
                InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast_menu")
            ],
            [
                InlineKeyboardButton(text="💰 Balance Inquiry", callback_data="admin_balance_inquiry_0"),
                InlineKeyboardButton(text="🔗 Work Links", callback_data="admin_work_links_0")
            ],
            [
                InlineKeyboardButton(text="🆘 Help Queries", callback_data="admin_help_list_0"),
                InlineKeyboardButton(text="👑 Manage Admins", callback_data="admin_manage_admins")
            ],
            [
                InlineKeyboardButton(text="🔗 Set Work Link", callback_data="admin_set_work"),
                InlineKeyboardButton(text="🔗 Set Proof Link", callback_data="admin_set_proof")
            ],
            [
                InlineKeyboardButton(text="📝 Set Notice", callback_data="admin_set_notice"), # NEW FEATURE: Set Notice
                InlineKeyboardButton(text="💾 Backup DB", callback_data="admin_backup")
            ],
            [
                InlineKeyboardButton(text=maintenance_text, callback_data="admin_toggle_maintenance"),
                InlineKeyboardButton(text="❌ Close Panel", callback_data="admin_close")
            ],
            [
                InlineKeyboardButton(text="🏠 Main Panel", callback_data="back_to_menu")
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
        
        async def background_registration():
            try:
                existing_by_id = await users_col.find_one({"user_id": user_id})
                is_pre_registered = False
                
                if not existing_by_id and username:
                    existing_by_user = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
                    if existing_by_user and existing_by_user.get("user_id") == 0:
                        is_pre_registered = True

                await register_user_if_not_exists(user_id, username, first_name)
                
                if not existing_by_id and not is_pre_registered and ADMIN_ID != 0:
                    notify_text = f"🆕 **New User Started the Bot!**\n\n👤 Name: {clean_md(first_name)}\n🔗 Username: @{clean_md(username)}\n🆔 ID: `{user_id}`"
                    try:
                        await bot.send_message(ADMIN_ID, notify_text, parse_mode="Markdown")
                    except Exception:
                        pass
            except Exception as bg_e:
                logger.error(f"Background registration error: {bg_e}")
                
        asyncio.create_task(background_registration())

        settings = await get_bot_settings()
        is_admin = await is_admin_user(user_id)
        
        text = (
            f"🏢 **Welcome to the Official Work Portal, {clean_md(first_name)}!** 🌟\n\n"
            "We provide a premium platform for professionals to monetize their Instagram presence through targeted ad campaigns.\n\n"
            "📊 **Your Dashboard Overview:**\n"
            "• Manage your workflow seamlessly.\n"
            "• Track your daily earnings & payouts.\n"
            "• Submit your completed tasks for rapid approval.\n\n"
            "👇 *Please select an option below to navigate your dashboard:*"
        )
        await message.answer(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"], is_admin), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in start command: {e}")

@router.callback_query(F.data == "withdrawal_list")
async def show_withdrawal_list(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        withdrawals, total_today, total_7days = await get_daily_withdrawals()
        today_date = datetime.now().strftime("%d %B %Y")
        
        text = f"📊 **Approved Withdrawals**\n\n"
        text += f"📅 **Last 7 Days Total:** ₹{total_7days:,}\n"
        text += f"💵 **Today's Total ({today_date}):** ₹{total_today:,}\n\n"
        text += f"📜 **Today's Recent Payments:**\n"
        
        for w in withdrawals:
            text += f"✅ **{w['name']}** - {w['amount_str']} at {w['time']}\n"
            
        await safe_edit_message(callback, text, InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in withdrawal_list: {e}")

@router.callback_query(F.data == "active_members")
async def show_active_members(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        user = await get_user(callback.from_user.id)
        is_active_user = user.get("is_active", False) if user else False
        current_user_name = clean_md(user.get("first_name", "User")) if is_active_user else None

        text = "🌟 **Our Active Working Members** 🌟\n\n"
        
        for month, names in FAKE_MEMBERS_BY_MONTH.items():
            if month == "September 2026":
                combined_names = names.copy()
                if current_user_name:
                    insert_idx = random.randint(0, len(combined_names) - 1)
                    combined_names.insert(insert_idx, current_user_name)
                
                text += f"📅 **{month} (Total: {len(combined_names)} Members)**\n"
                text += ", ".join(combined_names) + "\n\n"
            else:
                text += f"📅 **{month} ({len(names)} Members)**\n"
                text += ", ".join(names) + "\n\n"
                
        await safe_edit_message(callback, text, InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
        ))
    except Exception as e:
        logger.error(f"Error in active_members: {e}")

@router.callback_query(F.data == "my_balance")
async def show_balance(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        user = await get_user(callback.from_user.id)
        
        if not user or not user.get("is_active"):
            text = (
                "🚫 **Access Restricted**\n\n"
                "You are not currently employed with us as a verified staff member. "
                "This wallet feature and dashboard are restricted to official employees only.\n\n"
                "💼 *If you wish to join our team, please use the 'Apply to work' button on the main menu.*"
            )
            await safe_edit_message(callback, text, InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]]
            ))
            return

        balance = user.get("balance", 0)
        text = (
            f"💰 **My Wallet Balance**\n\n"
            f"👤 User: {clean_md(callback.from_user.first_name)}\n"
            f"💵 Current Balance: ₹{balance:,}"
        )
        await safe_edit_message(callback, text, InlineKeyboardMarkup(
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
        await callback.answer()
        text = (
            "💵 **Exchange Rate: $1 = ₹93 INR**\n\n"
            "Please select your preferred withdrawal method below:"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🏦 UPI", callback_data="withdraw_method_upi"),
                InlineKeyboardButton(text="🪙 Crypto", callback_data="withdraw_method_crypto")
            ],
            # FEATURE 7: BUG FIX - Changed back button to back_to_menu so non-staff don't get stuck
            [InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]
        ])
        
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in request_withdraw: {e}")

@router.callback_query(F.data.startswith("withdraw_method_"))
async def handle_withdraw_method(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        method = callback.data.split("_")[-1].upper()
        
        if method == "UPI":
            await state.set_state(WithdrawStates.waiting_for_upi)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="request_withdraw")]])
            await safe_edit_message(callback, "🏦 **UPI Withdrawal**\n\n👉 Please Add UPI ID below:", kb)
            
        elif method == "CRYPTO":
            await state.set_state(WithdrawStates.waiting_for_crypto)
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="request_withdraw")]])
            await safe_edit_message(callback, "🪙 **Crypto Withdrawal**\n\n👉 Please Add Address and Select Currency below:", kb)

    except Exception as e:
        logger.error(f"Error in withdraw method processing: {e}")

async def validate_withdrawal(message: Message, state: FSMContext) -> None:
    user = await get_user(message.from_user.id)
    
    if not user or not user.get("is_active"):
        await message.reply("🚫 Access Denied! This feature is only for our verified staff.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back to Main Menu", callback_data="back_to_menu")]]))
        await state.clear()
        return

    approval_date = user.get("approval_date")
    if not approval_date:
        approval_date = user.get("join_date")
        
    delta = datetime.now() - approval_date
    total_seconds = (timedelta(hours=96) - delta).total_seconds()
    
    if total_seconds > 0:
        days_left = int(total_seconds // 86400)
        hours_left = int((total_seconds % 86400) // 3600)
        time_str = f"{days_left} Days and {hours_left} Hours" if days_left > 0 else f"{hours_left} Hours"
        
        await message.reply(
            f"⏳ **You have not completed 96 hours yet.**\n\nYou need to wait 96 hours after joining to withdraw.\nTime remaining: {time_str}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="request_withdraw")]])
        )
        await state.clear()
        return

    balance = user.get("balance", 0)
    if balance < 3000:
        await message.reply(
            f"⚠️ **3k minimum withdrawal required.**\n\nYour current balance is only ₹{balance}. You need at least ₹3,000 to place a request.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="request_withdraw")]])
        )
        await state.clear()
        return

    await message.reply("✅ Your withdrawal request has been submitted to Admin! Processing takes 24-48 hours.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Main Menu", callback_data="back_to_menu")]]))
    await state.clear()

@router.message(WithdrawStates.waiting_for_upi)
async def process_withdraw_upi(message: Message, state: FSMContext) -> None:
    try:
        await validate_withdrawal(message, state)
    except Exception as e:
        logger.error(f"Error in process_withdraw_upi: {e}")

@router.message(WithdrawStates.waiting_for_crypto)
async def process_withdraw_crypto(message: Message, state: FSMContext) -> None:
    try:
        await validate_withdrawal(message, state)
    except Exception as e:
        logger.error(f"Error in process_withdraw_crypto: {e}")

# ==========================================
# STAFF WORK & SUBMISSION FLOW (FSM)
# ==========================================

@router.callback_query(F.data == "accept_tc")
async def accept_tc_handler(callback: CallbackQuery) -> None:
    try:
        await users_col.update_one({"user_id": callback.from_user.id}, {"$set": {"tc_accepted": True}})
        await callback.answer("✅ Terms & Conditions Accepted! Welcome to the team.", show_alert=True)
        # Re-trigger the staff menu logic directly
        await staff_only_menu(callback)
    except Exception as e:
        logger.error(f"Error in accept_tc_handler: {e}")

@router.callback_query(F.data == "staff_only_menu")
async def staff_only_menu(callback: CallbackQuery) -> None:
    try:
        user = await get_user(callback.from_user.id)
        
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied!\n\nYou are not in staff.", show_alert=True)
            return
            
        # Check if T&C is accepted
        if not user.get("tc_accepted", False):
            emp_id = user.get("emp_id", f"EMP-{random.randint(10000, 99999)}")
            if "emp_id" not in user:
                await users_col.update_one({"user_id": callback.from_user.id}, {"$set": {"emp_id": emp_id}})
            
            tc_text = (
                f"🏢 **Corporate Onboarding**\n\n"
                f"👤 **Employee ID:** `{emp_id}`\n\n"
                f"📜 **Terms & Conditions:**\n"
                f"1. Payments are provided within 96 hours of withdrawal request.\n"
                f"2. A minimum balance of ₹3,000 is required for withdrawal.\n"
                f"3. You must post Instagram stories daily as instructed.\n"
                f"4. If your Instagram account gets suspended, do not worry. We will still pay you for your work, and you can replace it with a new account.\n\n"
                f"Please accept these terms to continue to your dashboard."
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ I have agree with this terms and condition", callback_data="accept_tc")],
                [InlineKeyboardButton(text="« Cancel", callback_data="back_to_menu")]
            ])
            await safe_edit_message(callback, tc_text, kb)
            return

        await callback.answer()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🆕 New Work", callback_data="request_new_work")],
            [InlineKeyboardButton(text="📤 Submit Work", callback_data="submit_work_dashboard")],
            [InlineKeyboardButton(text="👤 My Section", callback_data="staff_my_section")],
            [InlineKeyboardButton(text="🆘 Help", callback_data="staff_help")],
            [InlineKeyboardButton(text="« Back", callback_data="back_to_menu")]
        ])
        
        text = "👨‍💼 **Staff Only Dashboard**\n\nWelcome to the staff portal. Manage your automated work batches, submit completed tasks, and track your daily earnings."
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in staff_only_menu: {e}")

@router.callback_query(F.data == "staff_faq")
async def staff_faq_handler(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        text = (
            "❓ **Frequently Asked Questions (FAQ)**\n\n"
            "**Q1: When will my payment arrive?**\n"
            "A: We process payments in a minimum of 96 hours after your joining. A minimum balance of ₹3,000 is also required to place a withdrawal request.\n\n"
            "**Q2: Why is the withdrawal 96 hours and minimum ₹3000?**\n"
            "A: Many users make different profiles and get fake views and other fake joinings, which causes a loss to our company. Therefore, a minimum 4-day (96 hours) and 3k balance requirement is kept so that there is no cheating or fraudulent activity.\n\n"
            "**Q3: Why does an account get banned or suspended?**\n"
            "A: Sometimes Instagram's automated system detects repetitive actions as bot behavior. If this happens, don't panic. You will still be paid for your completed work, and you can just replace the banned account with a new one to continue working.\n\n"
            "**Q4: How many reels do I need to upload per batch?**\n"
            "A: You must upload exactly 12 reels per batch (6 for each of the two accounts) as provided in your new work section."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back to Dashboard", callback_data="back_to_menu")]])
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in staff_faq_handler: {e}")

@router.callback_query(F.data == "staff_help")
async def staff_help_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(StaffHelpStates.waiting_for_message)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="staff_only_menu")]])
        text = "🆘 **Help & Support**\n\nPlease type your message or send a photo with a caption describing your issue. Admin will check and reply shortly."
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in staff_help_prompt: {e}")

@router.message(StaffHelpStates.waiting_for_message)
async def receive_help_message(message: Message, state: FSMContext) -> None:
    try:
        tkt_id = random.randint(10000, 99999)
        query_doc = {
            "user_id": message.from_user.id,
            "user_name": clean_md(message.from_user.first_name),
            "message_id": message.message_id,
            "text": message.text or message.caption or "[Media Message]",
            "status": "pending",
            "ticket_id": tkt_id,
            "timestamp": datetime.now()
        }
        await help_queries_col.insert_one(query_doc)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back to Dashboard", callback_data="staff_only_menu")]])
        
        # FEATURE 3: HR TEAM PERSONA
        reply_msg = f"✅ **Your support ticket #TKT-{tkt_id} has been created.**\n\nOur **[HR & Support Team]** will reply within 12-24 hours."
        await message.reply(reply_msg, reply_markup=kb)
        await state.clear()
    except Exception as e:
        logger.error(f"Error receiving help message: {e}")

# FEATURE 4: VIRTUAL ID CARD IN MY SECTION
@router.callback_query(F.data == "staff_my_section")
async def staff_my_section(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        user = await get_user(callback.from_user.id)
        
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied!", show_alert=True)
            return

        balance = user.get("balance", 0)
        emp_id = user.get("emp_id", "N/A")
        join_date_str = user.get("join_date", datetime.now()).strftime("%d %b %Y")
        status_text = "ACTIVE & VERIFIED" if user.get("is_active") else "INACTIVE"
        
        text = (
            f"🏢 **INSTA WORK ENTERPRISES - ID CARD**\n"
            f"----------------------------------------\n"
            f"📛 **Name:** {clean_md(callback.from_user.first_name)}\n"
            f"🆔 **EMP ID:** `{emp_id}`\n"
            f"📅 **Joining Date:** {join_date_str}\n"
            f"🟢 **Status:** {status_text}\n"
            f"----------------------------------------\n\n"
            f"💰 **Total Balance:** ₹{balance:,}\n"
            f"*(You can request a withdrawal below once minimum limits and hours are met)*"
        )
        
        # FEATURE 6: DAILY NOTICE BOARD BUTTON ADDED HERE
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Notice Board", callback_data="view_notice_board")],
            [InlineKeyboardButton(text="🏦 Withdrawal", callback_data="request_withdraw")],
            [InlineKeyboardButton(text="« Back", callback_data="staff_only_menu")]
        ])
        
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in staff_my_section: {e}")

# FEATURE 6: NOTICE BOARD USER HANDLER
@router.callback_query(F.data == "view_notice_board")
async def view_notice_board(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        doc = await settings_col.find_one({"_id": "notice_board"})
        text = doc.get("text", "No new updates or notices from the Admin at the moment.") if doc else "No new updates or notices from the Admin at the moment."
        
        msg = f"📢 **Daily Notice Board [Insta Work Enterprises]**\n\n{text}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="staff_my_section")]])
        await safe_edit_message(callback, msg, kb)
    except Exception as e:
        logger.error(f"Error viewing notice board: {e}")

@router.callback_query(F.data == "request_new_work")
async def request_new_work(callback: CallbackQuery, bot: Bot) -> None:
    try:
        user = await get_user(callback.from_user.id)
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied! This is for only our staff.", show_alert=True)
            return

        step = user.get("schedule_step", 0)
        last_work_time = user.get("last_work_time")
        approval_date = user.get("approval_date") or user.get("join_date", datetime.now())
        now = datetime.now()
        
        # UPGRADED: Independent cooldown logic. Strictly time-based (4h/6h/8h), ignoring manual admin approval status.
        if step == 0:
            next_allowed = approval_date + timedelta(hours=4)
        elif step == 1:
            next_allowed = last_work_time + timedelta(hours=6) if last_work_time else now + timedelta(hours=6)
        else:
            next_allowed = last_work_time + timedelta(hours=8) if last_work_time else now + timedelta(hours=8)

        if next_allowed and now < next_allowed:
            wait_time = next_allowed - now
            hours, remainder = divmod(int(wait_time.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            
            if step == 0:
                msg = f"⏳ 4 Hour Limit Block!\n\nYour limit opens in {hours} hours and {minutes} minutes.\n\nPlease retry after this time to get your new work."
            elif step == 1:
                msg = f"⏳ 6 Hour Limit Block!\n\n{hours} hours and {minutes} minutes remaining until your next batch limit opens."
            else:
                msg = f"⏳ 8 Hour Limit Block!\n\n{hours} hours and {minutes} minutes remaining until your next batch limit opens."
                
            await callback.answer(msg, show_alert=True)
            return

        # Safe to show processing state now that limits are passed
        await callback.answer("📥 Processing your work request...")
        
        # PREVENT SPAM CLICKING - Update DB lock immediately to prevent sending 15-16 videos
        await users_col.update_one(
            {"user_id": callback.from_user.id},
            {"$set": {"last_work_time": now}}
        )

        dump_settings = await settings_col.find_one({"_id": "dump_settings"})
        if not dump_settings:
            await callback.message.answer("⚠️ Admin hasn't configured the Dump Channel yet.")
            return

        chat_id = dump_settings.get("chat_id")
        base_msg_id = dump_settings.get("base_msg_id")
        total_videos = dump_settings.get("total_videos", 0)
        total_batches_available = total_videos // 6

        sent_batches = user.get("sent_batches", [])
        available_batches = [i for i in range(total_batches_available) if i not in sent_batches]

        actual_batches = 2 # Automatically deliver both batches (12 videos) without admin approval

        if len(available_batches) < actual_batches:
            await callback.message.answer("⚠️ Not enough new unique videos available in the Dump Channel. Please contact Admin.")
            # Revert the temporary lock if failed
            await users_col.update_one({"user_id": callback.from_user.id}, {"$set": {"last_work_time": last_work_time}})
            return

        await callback.message.answer(f"🚀 **New Work Assigned! Your batch is open.**\nDelivering {actual_batches} batches (6 reels each)...")
        
        selected_batches = random.sample(available_batches, actual_batches)
        
        # UPGRADED: Robust video counting to guarantee EXACTLY 12 videos are delivered, skipping broken/deleted items.
        for idx, batch_idx in enumerate(selected_batches, 1):
            await callback.message.answer(f"📦 **Batch {idx}**")
            
            start_msg_id = base_msg_id + (batch_idx * 6)
            success_count = 0
            attempts = 0
            current_msg_id = start_msg_id
            
            while success_count < 6 and attempts < 15: # Loop ensures exact 6 valid fetches
                try:
                    await bot.copy_message(
                        chat_id=callback.from_user.id,
                        from_chat_id=chat_id,
                        message_id=current_msg_id
                    )
                    success_count += 1
                    await asyncio.sleep(0.5) 
                except Exception as e:
                    logger.warning(f"Failed to copy msg {current_msg_id} from {chat_id}: {e}")
                
                current_msg_id += 1
                attempts += 1
            
            if success_count == 0:
                await callback.message.answer("⚠️ *Could not fetch videos for this batch.*", parse_mode="Markdown")

        sent_batches.extend(selected_batches)
        
        await users_col.update_one(
            {"user_id": callback.from_user.id},
            {"$set": {
                "sent_batches": sent_batches,
                "work_approved": False,
                "pending_second_batch": False,
                "notified_new_work": False,
                "has_submitted_current_work": False, 
                "notified_missed_4h": False,
                "notified_missed_6h": False,
                "notified_missed_8h": False
            }, "$inc": {"schedule_step": 1}}
        )
        
        await callback.message.answer("✅ **Work Delivered!**\n\nPost 6 account 6 reach for both accounts and submit work again.")

    except Exception as e:
        logger.error(f"Error in request_new_work: {e}")
        try:
            await callback.answer("An error occurred while fetching work.", show_alert=True)
        except:
            pass

# ---------------------------------------------
# UPGRADED SUBMIT WORK DASHBOARD (4 BUTTONS)
# ---------------------------------------------

async def render_submit_dashboard(callback_or_message, state: FSMContext) -> None:
    data = await state.get_data()
    l1 = data.get("link1")
    l2 = data.get("link2")
    p1 = data.get("photo1_id")
    p2 = data.get("photo2_id")

    btn1_text = "✅ Instagram First Link Added" if l1 else "🔗 Instagram First Link"
    btn2_text = "✅ Instagram Second Link Added" if l2 else "🔗 Instagram Second Link"
    btn3_text = "✅ Instagram First Page Photo Added" if p1 else "📸 Instagram First Page Photo"
    btn4_text = "✅ Instagram Second Page Photo Added" if p2 else "📸 Instagram Second Page Photo"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=btn1_text, callback_data="add_sub_link1")],
        [InlineKeyboardButton(text=btn2_text, callback_data="add_sub_link2")],
        [InlineKeyboardButton(text=btn3_text, callback_data="add_sub_photo1")],
        [InlineKeyboardButton(text=btn4_text, callback_data="add_sub_photo2")],
        [InlineKeyboardButton(text="🚀 Submit Work", callback_data="finalize_submission")],
        [InlineKeyboardButton(text="« Cancel", callback_data="staff_only_menu")]
    ])

    text = (
        "📝 **Work Submission Panel**\n\n"
        "Please provide all required links and photos by clicking the buttons below. "
        "Once all 4 items are filled, click **Submit Work**.\n\n"
        "*(Note: You have a 4-hour limit from your last successful submission before you can submit again.)*"
    )

    if isinstance(callback_or_message, CallbackQuery):
        await safe_edit_message(callback_or_message, text, kb)
    else:
        await callback_or_message.answer(text, reply_markup=kb, parse_mode="Markdown")

@router.callback_query(F.data == "submit_work_dashboard")
async def submit_work_dashboard_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        user = await get_user(callback.from_user.id)
        if not user or not user.get("is_active"):
            await callback.answer("🚫 Access Denied!", show_alert=True)
            return

        # 4-hour limit logic for work submission (Operates independently of admin approval)
        last_sub = await submissions_col.find_one(
            {"user_id": callback.from_user.id}, 
            sort=[("timestamp", -1)]
        )
        
        if last_sub:
            if last_sub.get("status") != "denied":
                time_since_sub = (datetime.now() - last_sub["timestamp"]).total_seconds() / 3600
                if time_since_sub < 4:
                    rem_hours = int(4 - time_since_sub)
                    await callback.answer(f"⏳ Limit Reached! You must wait {rem_hours} more hours before your next submission.", show_alert=True)
                    return

        await callback.answer()
        await state.set_state(WorkSubmission.dashboard)
        await state.update_data(link1=None, link2=None, photo1_id=None, photo2_id=None)
        await render_submit_dashboard(callback, state)
    except Exception as e:
        logger.error(f"Error in submit_work_dashboard_start: {e}")

@router.callback_query(F.data.startswith("add_sub_"))
async def prompt_submission_field(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        field = callback.data.split("_")[-1]
        
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back to Dashboard", callback_data="return_submit_dashboard")]])
        
        if field == "link1":
            await state.set_state(WorkSubmission.waiting_for_link1)
            await safe_edit_message(callback, "🔗 **Send your First Instagram Profile Link:**", cancel_kb)
        elif field == "link2":
            await state.set_state(WorkSubmission.waiting_for_link2)
            await safe_edit_message(callback, "🔗 **Send your Second Instagram Profile Link:**", cancel_kb)
        elif field == "photo1":
            await state.set_state(WorkSubmission.waiting_for_photo1)
            await safe_edit_message(callback, "📸 **Send your First Instagram Page Photo:**\n*(Must clearly show views)*", cancel_kb)
        elif field == "photo2":
            await state.set_state(WorkSubmission.waiting_for_photo2)
            await safe_edit_message(callback, "📸 **Send your Second Instagram Page Photo:**\n*(Must clearly show views)*", cancel_kb)
            
    except Exception as e:
        logger.error(f"Error prompting field {callback.data}: {e}")

@router.callback_query(F.data == "return_submit_dashboard")
async def return_to_submit_dashboard(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(WorkSubmission.dashboard)
    await render_submit_dashboard(callback, state)

@router.message(WorkSubmission.waiting_for_link1)
async def process_work_dash_link1(message: Message, state: FSMContext) -> None:
    await state.update_data(link1=message.text)
    await state.set_state(WorkSubmission.dashboard)
    await render_submit_dashboard(message, state)

@router.message(WorkSubmission.waiting_for_link2)
async def process_work_dash_link2(message: Message, state: FSMContext) -> None:
    await state.update_data(link2=message.text)
    await state.set_state(WorkSubmission.dashboard)
    await render_submit_dashboard(message, state)

@router.message(WorkSubmission.waiting_for_photo1, F.photo)
async def process_work_dash_photo1(message: Message, state: FSMContext) -> None:
    await state.update_data(photo1_id=message.photo[-1].file_id)
    await state.set_state(WorkSubmission.dashboard)
    await render_submit_dashboard(message, state)

@router.message(WorkSubmission.waiting_for_photo2, F.photo)
async def process_work_dash_photo2(message: Message, state: FSMContext) -> None:
    await state.update_data(photo2_id=message.photo[-1].file_id)
    await state.set_state(WorkSubmission.dashboard)
    await render_submit_dashboard(message, state)

@router.callback_query(F.data == "finalize_submission")
async def finalize_work_submission(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        data = await state.get_data()
        if not all([data.get("link1"), data.get("link2"), data.get("photo1_id"), data.get("photo2_id")]):
            await callback.answer("⚠️ You must fill all 4 fields before submitting!", show_alert=True)
            return
            
        await callback.answer("Submitting...")
        
        sub_doc = {
            "user_id": callback.from_user.id,
            "user_name": callback.from_user.first_name,
            "link1": data.get("link1"),
            "link2": data.get("link2"),
            "photo1_id": data.get("photo1_id"),
            "photo2_id": data.get("photo2_id"),
            "status": "pending", 
            "timestamp": datetime.now()
        }
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Main Dashboard", callback_data="staff_only_menu")]])
        await safe_edit_message(callback, "🎉 **Work submitted successfully!**\nAdmin will review your Unmarked work and update your payment. Once approved, you can receive your next work.", kb)
        await state.clear()
        
        async def save_submission_bg():
            try:
                await submissions_col.insert_one(sub_doc)
                await users_col.update_one(
                    {"user_id": callback.from_user.id},
                    {"$inc": {"submission_count": 1}, "$set": {"has_submitted_current_work": True}}
                )
            except Exception as bg_e:
                logger.error(f"Background save error: {bg_e}")
                
        asyncio.create_task(save_submission_bg())
        
    except Exception as e:
        logger.error(f"Error finalizing submission: {e}")
        await callback.answer("⚠️ Failed to submit work. Please try again.", show_alert=True)

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.clear()
        settings = await get_bot_settings()
        is_admin = await is_admin_user(callback.from_user.id)
        text = (
            f"🏢 **Welcome to the Official Work Portal, {clean_md(callback.from_user.first_name)}!** 🌟\n\n"
            "We provide a premium platform for professionals to monetize their Instagram presence through targeted ad campaigns.\n\n"
            "📊 **Your Dashboard Overview:**\n"
            "• Manage your workflow seamlessly.\n"
            "• Track your daily earnings & payouts.\n"
            "• Submit your completed tasks for rapid approval.\n\n"
            "👇 *Please select an option below to navigate your dashboard:*"
        )
        await safe_edit_message(callback, text, get_main_menu_keyboard(settings["work_link"], settings["proof_link"], is_admin))
    except Exception as e:
        logger.error(f"Error in back_to_menu: {e}")

# --- END OF PART 1 ---
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
        await message.reply(text, reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin command: {e}")

@router.callback_query(F.data == "open_admin_panel")
async def open_admin_panel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        if not await is_admin_user(callback.from_user.id):
            await callback.answer("🚫 Access Denied", show_alert=True)
            return
        await callback.answer()
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await safe_edit_message(callback, text, await get_admin_panel_keyboard())
    except Exception as e:
        logger.error(f"Error in open_admin_panel: {e}")

# --- MAINTENANCE TOGGLE LOGIC ---
@router.callback_query(F.data == "admin_toggle_maintenance")
async def toggle_maintenance_mode(callback: CallbackQuery) -> None:
    try:
        if not await is_admin_user(callback.from_user.id):
            await callback.answer("🚫 Access Denied", show_alert=True)
            return
            
        status_doc = await settings_col.find_one({"_id": "system_status"})
        current_status = status_doc.get("maintenance_mode", False) if status_doc else False
        new_status = not current_status
        
        await settings_col.update_one(
            {"_id": "system_status"},
            {"$set": {"maintenance_mode": new_status}},
            upsert=True
        )
        
        state_text = "ON 🟢" if new_status else "OFF 🔴"
        await callback.answer(f"Maintenance Mode is now {state_text}", show_alert=True)
        
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await safe_edit_message(callback, text, await get_admin_panel_keyboard())
        
    except Exception as e:
        logger.error(f"Error toggling maintenance mode: {e}")
        await callback.answer("⚠️ Error occurred.", show_alert=True)

@router.callback_query(F.data == "admin_stats")
async def admin_show_stats(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        total_users = await users_col.count_documents({})
        active_users = await users_col.count_documents({"is_active": True})
        
        today_start = datetime.combine(datetime.now().date(), datetime.min.time())
        joined_today = await users_col.count_documents({"join_date": {"$gte": today_start}})
        
        total_subs = await submissions_col.count_documents({})
        pending_subs = await submissions_col.count_documents({"status": "pending"})
        
        dump_settings = await settings_col.find_one({"_id": "dump_settings"})
        total_videos = dump_settings.get("total_videos", 0) if dump_settings else 0
        batches = total_videos // 6
        
        text = (
            "📊 **Bot Statistics**\n\n"
            f"👥 **Total Users:** {total_users}\n"
            f"✅ **Total Active Members:** {active_users}\n"
            f"🆕 **Joined Today:** {joined_today}\n\n"
            f"📥 **Total Submissions:** {total_subs}\n"
            f"⏳ **Unmarked (Pending) Submissions:** {pending_subs}\n"
            f"🔗 **Available Dump Batches:** {batches} ({total_videos} videos)"
        )
        await safe_edit_message(callback, text, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]]))
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")

# --- NEW HELP QUERIES LOGIC ---
@router.callback_query(F.data.startswith("admin_help_list_"))
async def admin_help_list(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        ITEMS_PER_PAGE = 10
        skip_count = page * ITEMS_PER_PAGE
        
        total_queries = await help_queries_col.count_documents({"status": "pending"})
        queries = await help_queries_col.find({"status": "pending"}).sort("timestamp", 1).skip(skip_count).limit(ITEMS_PER_PAGE).to_list(length=ITEMS_PER_PAGE)
        
        if not queries and page == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
            await safe_edit_message(callback, "✅ No pending help queries.", kb)
            return
            
        kb = InlineKeyboardBuilder()
        for q in queries:
            name = q.get("user_name", "User")
            qid = str(q["_id"])
            kb.button(text=f"🆘 {name}", callback_data=f"view_help_query_{qid}_{page}")
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_help_list_{page-1}"))
        if skip_count + ITEMS_PER_PAGE < total_queries:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_help_list_{page+1}"))
        
        if nav_row:
            kb.row(*nav_row)
            
        kb.row(InlineKeyboardButton(text="« Back", callback_data="admin_cancel"))
        kb.adjust(1)
        
        text = f"🆘 **Pending Help Queries (Page {page+1}):**\nSelect a user to view their request and reply:"
        await safe_edit_message(callback, text, kb.as_markup())
    except Exception as e:
        logger.error(f"Error in admin_help_list: {e}")

@router.callback_query(F.data.startswith("view_help_query_"))
async def view_help_query(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        parts = callback.data.split("_")
        qid = parts[3]
        page = int(parts[4]) if len(parts) > 4 else 0
        
        query = await help_queries_col.find_one({"_id": ObjectId(qid)})
        if not query:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"admin_help_list_{page}")]])
            await safe_edit_message(callback, "⚠️ Query not found or already resolved.", kb)
            return
            
        user_name = query.get("user_name", "Unknown")
        user_id = query.get("user_id", "Unknown")
        q_text = query.get("text", "No text provided.")
        ts = query.get("timestamp", datetime.now()).strftime("%d %b, %I:%M %p")
        ticket_id = query.get("ticket_id", "Unknown")
        
        text = (
            f"🆘 **Help Query Details** (#TKT-{ticket_id})\n\n"
            f"👤 **User:** {user_name}\n"
            f"🆔 **ID:** `{user_id}`\n"
            f"🕒 **Time:** {ts}\n\n"
            f"📝 **Message:**\n{q_text}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Reply to User", callback_data=f"reply_help_query_{qid}")],
            [InlineKeyboardButton(text="✅ Mark as Resolved", callback_data=f"resolve_help_query_{qid}_{page}")],
            [InlineKeyboardButton(text="« Back to List", callback_data=f"admin_help_list_{page}")]
        ])
        
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error viewing help query: {e}")

@router.callback_query(F.data.startswith("resolve_help_query_"))
async def resolve_help_query(callback: CallbackQuery) -> None:
    try:
        parts = callback.data.split("_")
        qid = parts[3]
        page = parts[4]
        
        await help_queries_col.update_one({"_id": ObjectId(qid)}, {"$set": {"status": "resolved"}})
        await callback.answer("✅ Query marked as resolved!", show_alert=True)
        
        # Mocking callback to jump back to list seamlessly
        callback.data = f"admin_help_list_{page}"
        await admin_help_list(callback)
    except Exception as e:
        logger.error(f"Error resolving help query: {e}")

@router.callback_query(F.data.startswith("reply_help_query_"))
async def reply_help_query_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        qid = callback.data.split("_")[-1]
        query = await help_queries_col.find_one({"_id": ObjectId(qid)})
        
        if not query:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_help_list_0")]])
            await safe_edit_message(callback, "⚠️ Query not found.", kb)
            return
            
        await state.set_state(AdminStates.waiting_for_help_reply)
        await state.update_data(help_query_id=qid, help_user_id=query["user_id"])
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data=f"view_help_query_{qid}_0")]])
        text = (
            f"💬 **Reply to {query.get('user_name', 'User')}**\n\n"
            f"Type your message below (or send a photo/video/voice). It will be sent directly to the user."
        )
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error prompting help reply: {e}")

@router.message(AdminStates.waiting_for_help_reply)
async def send_help_reply(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        uid = data.get("help_user_id")
        qid = data.get("help_query_id")
        
        if not uid or not qid:
            await message.reply("⚠️ Error: Session expired.", reply_markup=await get_admin_panel_keyboard())
            await state.clear()
            return
            
        await bot.send_message(uid, "📩 **[HR & Support Team] Reply to your Help Request:**")
        await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
        
        await help_queries_col.update_one({"_id": ObjectId(qid)}, {"$set": {"status": "resolved"}})
        
        await message.reply("✅ **Reply sent successfully and query marked as resolved!**", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error sending help reply: {e}")
        await message.reply("⚠️ Failed to send reply. The user might have blocked the bot.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()

# --- BACKUP SYSTEM LOGIC ---
@router.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer("Generating Backup...")
        
        users = await users_col.find({}, {"_id": 0}).to_list(length=None)
        dump_settings = await settings_col.find_one({"_id": "dump_settings"}, {"_id": 0})
        
        for u in users:
            for k, v in u.items():
                if isinstance(v, datetime):
                    u[k] = v.isoformat()
        
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            "users": users,
            "dump_settings": dump_settings,
            "info": "MongoDB Auto-Sync is ON. Data is safe even on VPS restart."
        }
        
        json_data = json.dumps(backup_data, indent=4).encode('utf-8')
        file = BufferedInputFile(json_data, filename=f"bot_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json")
        
        await bot.send_document(
            callback.from_user.id, 
            document=file, 
            caption="💾 **Database Backup Generated!**\n\n*Note:* Data automatically syncs via MongoDB, no VPS files will be lost.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error generating backup: {e}")
        await callback.answer("⚠️ Failed to generate backup.", show_alert=True)

# --- DP STORAGE LOGIC ---
@router.callback_query(F.data == "admin_dp_storage_menu")
async def dp_storage_menu(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📁 Step 1", callback_data="dp_view_step1"), InlineKeyboardButton(text="📁 Step 2", callback_data="dp_view_step2")],
            [InlineKeyboardButton(text="📁 Step 3", callback_data="dp_view_step3"), InlineKeyboardButton(text="📁 Step 4", callback_data="dp_view_step4")],
            [InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]
        ])
        await safe_edit_message(callback, "🖼️ **DP Storage (Steps)**\n\nStorage completely synced in Database. Select a step:", kb)
    except Exception as e:
        logger.error(f"Error in dp_storage_menu: {e}")

@router.callback_query(F.data.startswith("dp_view_"))
async def view_dp_step(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        step = callback.data.split("_")[-1]
        
        media_data = await load_media()
        media_items = media_data.get("dp_storage", {}).get(step, [])
        text_items = await dp_texts_col.count_documents({"step": step})
        
        total_items = len(media_items) + text_items
        
        text = f"📁 **{step.capitalize()} Storage**\nTotal Items: `{total_items}` (Media: {len(media_items)}, Texts: {text_items})\n\nWhat would you like to do?"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add", callback_data=f"dp_add_{step}"), InlineKeyboardButton(text="👁️ View All", callback_data=f"dp_show_{step}_0")],
            [InlineKeyboardButton(text="🗑️ Clear Step", callback_data=f"dp_clear_{step}")],
            [InlineKeyboardButton(text="« Back", callback_data="admin_dp_storage_menu")]
        ])
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in view_dp_step: {e}")

@router.callback_query(F.data.startswith("dp_add_"))
async def add_dp_step_media(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        step = callback.data.split("_")[-1]
        await state.set_state(AdminStates.waiting_for_dp_storage_media)
        await state.update_data(dp_step=step)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data=f"dp_view_{step}")]])
        text = (
            f"📤 **Adding to {step.capitalize()}**\n\n"
            f"👉 Please send a Photo, Video, or Text message.\n"
            f"*(Everything is safely stored inside Database for persistence)*"
        )
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in add_dp_step_media: {e}")

@router.message(AdminStates.waiting_for_dp_storage_media)
async def receive_dp_storage_media(message: Message, state: FSMContext) -> None:
    try:
        data = await state.get_data()
        step = data.get("dp_step")
        if not step:
            return

        is_text = False
        file_id = None
        media_type = None

        if message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"
        elif message.text:
            file_id = message.text
            media_type = "text"
            is_text = True

        if not file_id:
            await message.reply("⚠️ Unsupported format. Please send a Photo, Video, or Text.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"dp_view_{step}")]]))
            return

        if is_text:
            await dp_texts_col.insert_one({
                "step": step,
                "text": file_id,
                "timestamp": datetime.now()
            })
            save_msg = f"✅ Text saved to DB under **{step.capitalize()}**!"
        else:
            media_data = await load_media()
            media_data["dp_storage"][step].append({"type": media_type, "content": file_id})
            await save_media(media_data)
            save_msg = f"✅ Media ID saved to DB under **{step.capitalize()}**!"

        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"dp_view_{step}")]])
        await message.reply(f"{save_msg}\n\nYou can keep sending more data to save, or go back.", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in receive_dp_storage_media: {e}")

@router.callback_query(F.data.startswith("dp_show_"))
async def show_dp_step_media_paginated(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer()
        parts = callback.data.split("_")
        step = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
        
        media_data = await load_media()
        media_items = media_data.get("dp_storage", {}).get(step, [])
        text_docs = await dp_texts_col.find({"step": step}).sort("timestamp", 1).to_list(length=None)
        
        combined_items = media_items + [{"type": "text", "content": doc["text"]} for doc in text_docs]
        
        if not combined_items:
            await callback.message.answer(f"⚠️ **{step.capitalize()} is empty.**", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"dp_view_{step}")]]))
            return

        ITEMS_PER_PAGE = 5
        total_items = len(combined_items)
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        
        page_items = combined_items[start_idx:end_idx]
        
        await callback.message.answer(f"📂 **{step.capitalize()} (Page {page+1})** - Showing {len(page_items)} items:")
        
        for item in page_items:
            m_type = item["type"]
            content = item["content"]
            try:
                if m_type == "photo":
                    await bot.send_photo(callback.from_user.id, photo=content)
                elif m_type == "video":
                    await bot.send_video(callback.from_user.id, video=content)
                elif m_type == "text":
                    await bot.send_message(callback.from_user.id, text=content, disable_web_page_preview=True)
            except Exception as ex:
                logger.warning(f"Failed to send {m_type} from storage: {ex}")
            await asyncio.sleep(0.3)
            
        nav_kb = InlineKeyboardBuilder()
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"dp_show_{step}_{page-1}"))
        if end_idx < total_items:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"dp_show_{step}_{page+1}"))
            
        if nav_row:
            nav_kb.row(*nav_row)
        nav_kb.row(InlineKeyboardButton(text="« Back", callback_data=f"dp_view_{step}"))
        
        await callback.message.answer(f"Navigation for {step.capitalize()}:", reply_markup=nav_kb.as_markup())
            
    except Exception as e:
        logger.error(f"Error in show_dp_step_media_paginated: {e}")

@router.callback_query(F.data.startswith("dp_clear_"))
async def clear_dp_step(callback: CallbackQuery) -> None:
    try:
        step = callback.data.split("_")[-1]
        
        media_data = await load_media()
        media_data["dp_storage"][step] = []
        await save_media(media_data)
        
        await dp_texts_col.delete_many({"step": step})
        
        await callback.answer(f"✅ {step.capitalize()} cleared successfully!", show_alert=True)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add", callback_data=f"dp_add_{step}"), InlineKeyboardButton(text="👁️ View All", callback_data=f"dp_show_{step}_0")],
            [InlineKeyboardButton(text="🗑️ Clear Step", callback_data=f"dp_clear_{step}")],
            [InlineKeyboardButton(text="« Back", callback_data="admin_dp_storage_menu")]
        ])
        await safe_edit_message(callback, f"📁 **{step.capitalize()} Storage**\nTotal Items: `0`\n\nWhat would you like to do?", kb)
    except Exception as e:
        logger.error(f"Error in clear_dp_step: {e}")

# --- DP BANK MENUS (PAGINATED) ---
@router.callback_query(F.data == "admin_dp_bank_menu")
async def dp_bank_menu(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        media_data = await load_media()
        items = media_data.get("dp_bank", [])
        
        text = f"🏦 **DP Bank**\nTotal Photos: `{len(items)}`\n\nManage your massive collection of DPs:"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Photo", callback_data="dpbank_add")],
            [InlineKeyboardButton(text="🎲 Random 1", callback_data="dpbank_random"), InlineKeyboardButton(text="👁️ View All", callback_data="dpbank_viewall_0")],
            [InlineKeyboardButton(text="🗑️ Clear Bank", callback_data="dpbank_clear")],
            [InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]
        ])
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in dp_bank_menu: {e}")

@router.callback_query(F.data == "dpbank_add")
async def add_dpbank_photo(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_dp_bank_media)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="admin_dp_bank_menu")]])
        await safe_edit_message(callback, "📤 **Adding to DP Bank**\n\nPlease send a **Photo** to store it safely in the DB:", kb)
    except Exception as e:
        logger.error(f"Error in add_dpbank_photo: {e}")

@router.message(AdminStates.waiting_for_dp_bank_media)
async def receive_dp_bank_photo(message: Message, state: FSMContext) -> None:
    try:
        if not message.photo:
            await message.reply("⚠️ **Photos only!** Please send a photo.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu")]]))
            return

        file_id = message.photo[-1].file_id
        media_data = await load_media()
        media_data["dp_bank"].append(file_id)
        await save_media(media_data)

        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu")]])
        await message.reply("✅ Photo ID saved to DB DP Bank!\n\nYou can keep sending more photos.", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in receive_dp_bank_photo: {e}")

@router.callback_query(F.data == "dpbank_random")
async def show_dpbank_random(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer()
        media_data = await load_media()
        items = media_data.get("dp_bank", [])
        
        if not items:
            await callback.message.answer("⚠️ DP Bank is empty.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu")]]))
            return
            
        random_photo = random.choice(items)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu")]])
        await bot.send_photo(callback.from_user.id, photo=random_photo, caption="🎲 **Random Photo from DP Bank**", reply_markup=kb)
    except Exception as e:
        logger.error(f"Error in show_dpbank_random: {e}")

@router.callback_query(F.data.startswith("dpbank_viewall_"))
async def show_dpbank_all_paginated(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer()
        parts = callback.data.split("_")
        page = int(parts[2]) if len(parts) > 2 else 0
        
        media_data = await load_media()
        items = media_data.get("dp_bank", [])
        
        if not items:
            await callback.message.answer("⚠️ DP Bank is empty.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu")]]))
            return
            
        ITEMS_PER_PAGE = 5
        total_items = len(items)
        start_idx = page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        
        page_items = items[start_idx:end_idx]
        await callback.message.answer(f"🏦 **DP Bank (Page {page+1})** - Showing {len(page_items)} photos:")
        
        for photo_id in page_items:
            try:
                await bot.send_photo(callback.from_user.id, photo=photo_id)
            except Exception as ex:
                logger.warning(f"Failed to send bank photo: {ex}")
            await asyncio.sleep(0.3)
            
        nav_kb = InlineKeyboardBuilder()
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"dpbank_viewall_{page-1}"))
        if end_idx < total_items:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"dpbank_viewall_{page+1}"))
            
        if nav_row:
            nav_kb.row(*nav_row)
        nav_kb.row(InlineKeyboardButton(text="« Back", callback_data="admin_dp_bank_menu"))
        
        await callback.message.answer("Navigation:", reply_markup=nav_kb.as_markup())
            
    except Exception as e:
        logger.error(f"Error in show_dpbank_all: {e}")

@router.callback_query(F.data == "dpbank_clear")
async def clear_dpbank(callback: CallbackQuery) -> None:
    try:
        media_data = await load_media()
        media_data["dp_bank"] = []
        await save_media(media_data)
        await callback.answer("✅ DP Bank cleared successfully!", show_alert=True)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Photo", callback_data="dpbank_add")],
            [InlineKeyboardButton(text="🎲 Random 1", callback_data="dpbank_random"), InlineKeyboardButton(text="👁️ View All", callback_data="dpbank_viewall_0")],
            [InlineKeyboardButton(text="🗑️ Clear Bank", callback_data="dpbank_clear")],
            [InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]
        ])
        await safe_edit_message(callback, "🏦 **DP Bank**\nTotal Photos: `0`\n\nManage your massive collection of DPs:", kb)
    except Exception as e:
        logger.error(f"Error in clear_dpbank: {e}")

# --- SINGLE DUMP CHANNEL LOGIC ---
@router.callback_query(F.data == "admin_set_dump_channel")
async def admin_set_dump_channel_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_dump_channel_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        text = (
            "📥 **Set Dump Channel**\n\n"
            "To accurately fetch videos, please **FORWARD** the **FIRST** video message from your Dump Channel here.\n\n"
            "*(Alternatively, if it's a public channel, you can send the raw message link like `https://t.me/c/123456789/2`)*\n\n"
            "⚠️ *Invite links (like `t.me/+xyz`) will not work directly.*"
        )
        await safe_edit_message(callback, text, cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_set_dump_channel_prompt: {e}")

@router.message(AdminStates.waiting_for_dump_channel_link)
async def admin_set_dump_channel_link(message: Message, state: FSMContext) -> None:
    try:
        chat_id = None
        msg_id = None

        if message.forward_origin:
            if message.forward_origin.type == "channel":
                chat_id = message.forward_origin.chat.id
                msg_id = message.forward_origin.message_id
                
        if not chat_id and message.text:
            link = message.text.strip()
            
            if "joinchat" in link or "+" in link:
                await message.reply(
                    "⚠️ **Invite Link Detected!**\n\n"
                    "Invite links do not contain a message ID. Please **FORWARD** the first video directly from your dump channel to me instead.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="admin_cancel")]])
                )
                return
                
            chat_id, msg_id = parse_telegram_link(link)
            
        if not chat_id or not msg_id:
            await message.reply(
                "⚠️ Invalid format. Please either **FORWARD** a video directly from the channel, or ensure the link looks like `https://t.me/c/123456789/2`.", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="admin_cancel")]])
            )
            return
        
        await state.update_data(dump_chat_id=chat_id, dump_base_msg_id=msg_id)
        await state.set_state(AdminStates.waiting_for_dump_total_videos)
        await message.reply("✅ Channel & Base Message accepted.\n\nNow, please send the **TOTAL number of videos** uploaded in this channel (e.g., `300`):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="admin_cancel")]]))
    except Exception as e:
        logger.error(f"Error in admin_set_dump_channel_link: {e}")

@router.message(AdminStates.waiting_for_dump_total_videos)
async def admin_set_dump_total_videos(message: Message, state: FSMContext) -> None:
    try:
        total_videos = int(message.text.strip())
        if total_videos < 6:
            await message.reply("⚠️ Total videos must be at least 6.")
            return
        
        data = await state.get_data()
        chat_id = data["dump_chat_id"]
        base_msg_id = data["dump_base_msg_id"]
        
        await settings_col.update_one(
            {"_id": "dump_settings"},
            {"$set": {
                "chat_id": chat_id,
                "base_msg_id": base_msg_id,
                "total_videos": total_videos
            }},
            upsert=True
        )
        
        batches = total_videos // 6
        success_msg = (
            f"✅ **Dump Channel Configured Successfully!**\n\n"
            f"📌 Chat ID: `{chat_id}`\n"
            f"📌 Base Msg ID: `{base_msg_id}`\n"
            f"📌 Total Videos: `{total_videos}`\n"
            f"📦 Total Batches Available: `{batches}`"
        )
        await message.reply(success_msg, reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.reply("⚠️ Please send a valid number.")
    except Exception as e:
        logger.error(f"Error in admin_set_dump_total_videos: {e}")


# --- PAGINATED UNMARKED & MARKED SUBMISSIONS LOGIC (WITH CURRENT BALANCE) ---
@router.callback_query(F.data.startswith("admin_unmarked_subs_"))
async def admin_unmarked_subs(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        ITEMS_PER_PAGE = 10
        skip_count = page * ITEMS_PER_PAGE
        
        pipeline = [
            {"$match": {"status": "pending"}},
            {"$sort": {"timestamp": -1}}, 
            {"$group": {
                "_id": "$user_id",
                "user_name": {"$first": "$user_name"},
                "count": {"$sum": 1},
                "latest": {"$first": "$timestamp"}
            }},
            {"$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "user_info"
            }},
            {"$unwind": {"path": "$user_info", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"balance": {"$ifNull": ["$user_info.balance", 0]}}},
            {"$sort": {"latest": -1}},
            {"$skip": skip_count},
            {"$limit": ITEMS_PER_PAGE}
        ]
        
        total_pipeline = [
            {"$match": {"status": "pending"}},
            {"$group": {"_id": "$user_id"}}
        ]
        total_users_cursor = submissions_col.aggregate(total_pipeline)
        total_users_list = await total_users_cursor.to_list(length=None)
        total_users = len(total_users_list)

        subs_cursor = submissions_col.aggregate(pipeline)
        grouped_subs = await subs_cursor.to_list(length=ITEMS_PER_PAGE)
        
        if not grouped_subs and page == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
            await safe_edit_message(callback, "✅ No Unmarked (Pending) work submissions.", kb)
            return
            
        kb = InlineKeyboardBuilder()
        for s in grouped_subs:
            kb.button(text=f"📄 {s['user_name']} - ₹{s.get('balance', 0)} ({s['count']} subs)", callback_data=f"view_unmarked_{s['_id']}_0")
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"admin_unmarked_subs_{page-1}"))
        if skip_count + ITEMS_PER_PAGE < total_users:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_unmarked_subs_{page+1}"))
        
        if nav_row:
            kb.row(*nav_row)
            
        kb.row(InlineKeyboardButton(text="« Back", callback_data="admin_cancel"))
        kb.adjust(1)
        
        text = f"📋 **Unmarked Work Submissions (Page {page+1}):**\nClick on a user to review their work:"
        await safe_edit_message(callback, text, kb.as_markup())
    except Exception as e:
        logger.error(f"Error in admin_unmarked_subs: {e}")

@router.callback_query(F.data.startswith("admin_marked_subs_"))
async def admin_marked_subs(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        ITEMS_PER_PAGE = 10
        skip_count = page * ITEMS_PER_PAGE
        
        pipeline = [
            {"$match": {"status": {"$in": ["accepted", "denied"]}}},
            {"$sort": {"timestamp": -1}}, 
            {"$group": {
                "_id": "$user_id",
                "user_name": {"$first": "$user_name"},
                "count": {"$sum": 1},
                "latest": {"$first": "$timestamp"}
            }},
            {"$lookup": {
                "from": "users",
                "localField": "_id",
                "foreignField": "user_id",
                "as": "user_info"
            }},
            {"$unwind": {"path": "$user_info", "preserveNullAndEmptyArrays": True}},
            {"$addFields": {"balance": {"$ifNull": ["$user_info.balance", 0]}}},
            {"$sort": {"latest": -1}},
            {"$skip": skip_count},
            {"$limit": ITEMS_PER_PAGE}
        ]

        total_pipeline = [
            {"$match": {"status": {"$in": ["accepted", "denied"]}}},
            {"$group": {"_id": "$user_id"}}
        ]
        total_users_cursor = submissions_col.aggregate(total_pipeline)
        total_users_list = await total_users_cursor.to_list(length=None)
        total_users = len(total_users_list)

        subs_cursor = submissions_col.aggregate(pipeline)
        grouped_subs = await subs_cursor.to_list(length=ITEMS_PER_PAGE)
        
        if not grouped_subs and page == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
            await safe_edit_message(callback, "✅ No Marked work submissions found.", kb)
            return
            
        kb = InlineKeyboardBuilder()
        for s in grouped_subs:
            kb.button(text=f"📁 {s['user_name']} - ₹{s.get('balance', 0)} ({s['count']} subs)", callback_data=f"view_marked_{s['_id']}_0")
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"admin_marked_subs_{page-1}"))
        if skip_count + ITEMS_PER_PAGE < total_users:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_marked_subs_{page+1}"))
        
        if nav_row:
            kb.row(*nav_row)
            
        kb.row(InlineKeyboardButton(text="« Back", callback_data="admin_cancel"))
        kb.adjust(1)
        
        text = f"📁 **Marked Work Submissions (History Page {page+1}):**\nClick on a user to view their processed history:"
        await safe_edit_message(callback, text, kb.as_markup())
    except Exception as e:
        logger.error(f"Error in admin_marked_subs: {e}")

# --- CHECK NEXT IMPLEMENTATION & CHECK ALL PAYMENT ---
@router.callback_query(F.data.startswith("view_unmarked_"))
async def admin_view_unmarked_sub(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer() 
        parts = callback.data.split("_")
        
        if len(parts) == 3:
            user_id = int(parts[2])
            skip = 0
        else:
            user_id = int(parts[2])
            skip = int(parts[3])

        total_pending = await submissions_col.count_documents({"user_id": user_id, "status": "pending"})
        
        if total_pending == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_unmarked_subs_0")]])
            await safe_edit_message(callback, "⚠️ No unmarked submissions remaining for this user.", kb)
            return
            
        if skip >= total_pending:
            skip = 0
            
        # UPGRADED: sort("timestamp", -1) - Newest work first check
        subs_list = await submissions_col.find({"user_id": user_id, "status": "pending"}).sort("timestamp", -1).skip(skip).limit(1).to_list(1)
        
        if not subs_list:
            await callback.answer("⚠️ Could not load submission.", show_alert=True)
            return
            
        sub = subs_list[0]
        
        # Getting the user's current balance to display right next to the name
        user_doc = await users_col.find_one({"user_id": user_id})
        balance = user_doc.get("balance", 0) if user_doc else 0
        
        l1 = clean_md(str(sub.get('link1', sub.get('link', 'N/A'))))
        l2 = clean_md(str(sub.get('link2', 'N/A')))
        name = clean_md(str(sub.get('user_name', 'Unknown')))
        
        if len(l1) > 200: l1 = l1[:197] + "..."
        if len(l2) > 200: l2 = l2[:197] + "..."
        
        caption1 = (
            f"👤 **User:** {name} - ₹{balance}\n"
            f"🆔 **ID:** `{sub.get('user_id')}`\n"
            f"📌 **Status:** UNMARKED ({skip + 1} of {total_pending})\n\n"
            f"🔗 **First Profile:** {l1}"
        )
        caption2 = f"🔗 **Second Profile:** {l2}"
        
        sub_id = str(sub["_id"])
        
        action_kb = InlineKeyboardBuilder()
        action_kb.row(
            InlineKeyboardButton(text="✅ Accept", callback_data=f"accept_sub_{sub_id}"),
            InlineKeyboardButton(text="⏭️ Skip Payment", callback_data=f"skip_sub_{sub_id}")
        )
        # UPGRADED: Deny will now apply to all pending submissions
        action_kb.row(InlineKeyboardButton(text="❌ Deny All Work", callback_data=f"deny_sub_{sub_id}"))
        
        action_kb.row(InlineKeyboardButton(text="✅ Check All & Payment", callback_data=f"accept_all_{user_id}"))
        
        nav_row = []
        if total_pending > 1:
            prev_skip = skip - 1 if skip > 0 else total_pending - 1
            next_skip = skip + 1 if skip < total_pending - 1 else 0
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev Sub", callback_data=f"view_unmarked_{user_id}_{prev_skip}"))
            nav_row.append(InlineKeyboardButton(text="Check Next ➡️", callback_data=f"view_unmarked_{user_id}_{next_skip}"))
            
        if nav_row:
            action_kb.row(*nav_row)
            
        action_kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_unmarked_subs_0"))
        
        photo1_id = sub.get("photo1_id")
        photo2_id = sub.get("photo2_id")
        
        try:
            if callback.message.photo or callback.message.video or callback.message.document:
                await callback.message.delete()
                
            if photo1_id and photo2_id:
                await bot.send_photo(chat_id=callback.from_user.id, photo=photo1_id, caption=caption1, parse_mode="Markdown")
                await bot.send_photo(chat_id=callback.from_user.id, photo=photo2_id, caption=caption2, reply_markup=action_kb.as_markup(), parse_mode="Markdown")
            else: 
                photo_id = sub.get("photo_id")
                if photo_id:
                    cap = f"{caption1}\n🔗 **Second Profile:** {l2}"
                    await bot.send_photo(chat_id=callback.from_user.id, photo=photo_id, caption=cap, reply_markup=action_kb.as_markup(), parse_mode="Markdown")
                else:
                    await bot.send_message(chat_id=callback.from_user.id, text=f"{caption1}\n{caption2}", reply_markup=action_kb.as_markup(), parse_mode="Markdown")
        except Exception as ex:
            logger.error(f"Error sending submission details to admin: {ex}")
            await callback.answer("⚠️ Failed to display submission. Check logs.", show_alert=True)
    except Exception as e:
        logger.error(f"Error opening unmarked submission: {e}")

# --- ACCEPT ALL & PAYMENT ---
@router.callback_query(F.data.startswith("accept_all_"))
async def admin_accept_all_sub(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer("Enter total balance to add.") 
        user_id = int(callback.data.split("_")[-1])
        
        await state.set_state(AdminStates.waiting_for_all_submission_balance)
        await state.update_data(target_user_id=user_id)
        
        prompt_text = "\n\n✅ **STATUS: CHECK ALL & PAYMENT**\n\n👉 **Type the TOTAL balance to add for ALL pending work:**"
        
        try:
            if callback.message.caption:
                await callback.message.edit_caption(
                    caption=callback.message.caption + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
            else:
                await callback.message.edit_text(
                    text=callback.message.text + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error in accept_all_sub: {e}")

@router.message(AdminStates.waiting_for_all_submission_balance)
async def process_all_submission_balance(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        if not message.text:
            await message.reply("⚠️ Please enter a valid numerical amount.")
            return
        
        try:
            amount = int(message.text.strip())
        except ValueError:
            await message.reply("⚠️ Please enter a valid number (e.g., 500).")
            return
                
        data = await state.get_data()
        target_id = data.get("target_user_id")
        
        if target_id and amount >= 0:
            await submissions_col.update_many({"user_id": target_id, "status": "pending"}, {"$set": {"status": "accepted"}})
            # Denying sets it true, accepting sets it true
            await users_col.update_one({"user_id": target_id}, {"$set": {"work_approved": True}, "$inc": {"balance": amount}})
            
            async def notify_user():
                notify_text = f"🎉 **Your all work is successfully processed!**\n\n💰 **Balance Added:** ₹{amount}\n\nYou can now request your next batch."
                try:
                    await bot.send_message(target_id, notify_text)
                except Exception as e:
                    logger.error(f"Could not notify user {target_id}: {e}")
            asyncio.create_task(notify_user())
            
        await state.clear()
        
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_unmarked_subs_0"))
        kb.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="open_admin_panel"))

        await message.reply(f"✅ Successfully checked ALL work and added ₹{amount} to User `{target_id}`'s balance.", parse_mode="Markdown", reply_markup=kb.as_markup())
        
    except Exception as e:
        logger.error(f"Error adding all sub balance: {e}")
        await state.clear()

@router.callback_query(F.data.startswith("view_marked_"))
async def admin_view_marked_sub(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer()
        parts = callback.data.split("_")
        
        if len(parts) == 3:
            user_id = int(parts[2])
            skip = 0
        else:
            user_id = int(parts[2])
            skip = int(parts[3])

        total_marked = await submissions_col.count_documents({"user_id": user_id, "status": {"$in": ["accepted", "denied"]}})
        
        if total_marked == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_marked_subs_0")]])
            await safe_edit_message(callback, "⚠️ History empty.", kb)
            return
            
        if skip >= total_marked:
            skip = 0

        # UPGRADED: sort("timestamp", -1) - Already newest first here
        subs_list = await submissions_col.find({"user_id": user_id, "status": {"$in": ["accepted", "denied"]}}).sort("timestamp", -1).skip(skip).limit(1).to_list(1)
        
        if not subs_list:
            await callback.answer("⚠️ Submission not found.", show_alert=True)
            return
            
        sub = subs_list[0]
        status = "✅ ACCEPTED" if sub.get("status") == "accepted" else "❌ DENIED"
        
        # Getting the user's current balance to display right next to the name
        user_doc = await users_col.find_one({"user_id": user_id})
        balance = user_doc.get("balance", 0) if user_doc else 0
        
        l1 = clean_md(str(sub.get('link1', sub.get('link', 'N/A'))))
        l2 = clean_md(str(sub.get('link2', 'N/A')))
        name = clean_md(str(sub.get('user_name', 'Unknown')))
        
        if len(l1) > 200: l1 = l1[:197] + "..."
        if len(l2) > 200: l2 = l2[:197] + "..."
        
        caption1 = (
            f"👤 **User:** {name} - ₹{balance}\n"
            f"🆔 **ID:** `{sub.get('user_id')}`\n"
            f"📌 **Status:** {status} ({skip + 1} of {total_marked})\n"
            f"🕒 **Time:** {sub.get('timestamp').strftime('%d %b, %I:%M %p')}\n\n"
            f"🔗 **First Profile:** {l1}"
        )
        caption2 = f"🔗 **Second Profile:** {l2}"
        
        action_kb = InlineKeyboardBuilder()
        nav_row = []
        if total_marked > 1:
            prev_skip = skip - 1 if skip > 0 else total_marked - 1
            next_skip = skip + 1 if skip < total_marked - 1 else 0
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"view_marked_{user_id}_{prev_skip}"))
            nav_row.append(InlineKeyboardButton(text="Check Next ➡️", callback_data=f"view_marked_{user_id}_{next_skip}"))
            
        if nav_row:
            action_kb.row(*nav_row)
            
        action_kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_marked_subs_0"))
        
        photo1_id = sub.get("photo1_id")
        photo2_id = sub.get("photo2_id")

        try:
            if callback.message.photo or callback.message.video or callback.message.document:
                await callback.message.delete()
                
            if photo1_id and photo2_id:
                await bot.send_photo(chat_id=callback.from_user.id, photo=photo1_id, caption=caption1, parse_mode="Markdown")
                await bot.send_photo(chat_id=callback.from_user.id, photo=photo2_id, caption=caption2, reply_markup=action_kb.as_markup(), parse_mode="Markdown")
            else:
                photo_id = sub.get("photo_id")
                if photo_id:
                    await bot.send_photo(chat_id=callback.from_user.id, photo=photo_id, caption=f"{caption1}\n{caption2}", reply_markup=action_kb.as_markup(), parse_mode="Markdown")
                else:
                    await bot.send_message(chat_id=callback.from_user.id, text=f"{caption1}\n{caption2}", reply_markup=action_kb.as_markup(), parse_mode="Markdown")
        except Exception as ex:
            logger.error(f"Error sending marked sub details: {ex}")
    except Exception as e:
        logger.error(f"Error opening marked submission: {e}")

@router.callback_query(F.data.startswith("skip_sub_"))
async def admin_skip_sub(callback: CallbackQuery, bot: Bot) -> None:
    try:
        await callback.answer("Skipping payment...") 
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub or sub.get("status") != "pending":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_unmarked_subs_0")]])
            await safe_edit_message(callback, "⚠️ Submission already processed or not found.", kb)
            return
            
        user_id = sub["user_id"]
        await submissions_col.update_one({"_id": ObjectId(sub_id)}, {"$set": {"status": "accepted"}})
        await users_col.update_one({"user_id": user_id}, {"$set": {"work_approved": True}})
        
        async def skip_bg():
            try:
                await bot.send_message(user_id, "🎉 **Work Accepted!**\n\nYour recent work submission was successfully approved (No Balance Added). You can now request your next batch.")
            except Exception:
                pass
        asyncio.create_task(skip_bg())

        pending_left = await submissions_col.count_documents({"user_id": user_id, "status": "pending"})
        
        kb = InlineKeyboardBuilder()
        if pending_left > 0:
            kb.row(InlineKeyboardButton(text=f"Check Next ({pending_left} left) ➡️", callback_data=f"view_unmarked_{user_id}_0"))
        kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_unmarked_subs_0"))
        
        success_text = f"✅ Marked as Accepted (Skipped Payment) for User `{user_id}`.\n\nRemaining pending for this user: {pending_left}"
        try:
            if callback.message.caption:
                await callback.message.edit_caption(caption=callback.message.caption + "\n\n" + success_text, reply_markup=kb.as_markup())
            else:
                await callback.message.edit_text(text=callback.message.text + "\n\n" + success_text, reply_markup=kb.as_markup())
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error in skip_sub: {e}")

@router.callback_query(F.data.startswith("accept_sub_"))
async def admin_accept_sub(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer("Enter balance to add.") 
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub or sub.get("status") != "pending":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_unmarked_subs_0")]])
            await safe_edit_message(callback, "⚠️ Submission already processed or not found.", kb)
            return
            
        user_id = sub["user_id"]
        
        await state.set_state(AdminStates.waiting_for_submission_balance)
        await state.update_data(target_user_id=user_id, target_sub_id=sub_id)
        
        prompt_text = "\n\n✅ **STATUS: ACCEPTING**\n\n👉 **Type how much balance to add (e.g. 100):**"
        
        try:
            if callback.message.caption:
                await callback.message.edit_caption(
                    caption=callback.message.caption + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
            else:
                await callback.message.edit_text(
                    text=callback.message.text + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error in accept_sub: {e}")

@router.message(AdminStates.waiting_for_submission_balance)
async def process_submission_balance(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        if not message.text:
            await message.reply("⚠️ Please enter a valid numerical amount.")
            return
        
        try:
            amount = int(message.text.strip())
        except ValueError:
            await message.reply("⚠️ Please enter a valid number (e.g., 500).")
            return
                
        data = await state.get_data()
        target_id = data.get("target_user_id")
        sub_id = data.get("target_sub_id")
        
        if sub_id:
            await submissions_col.update_one({"_id": ObjectId(sub_id)}, {"$set": {"status": "accepted"}})
        if target_id and amount > 0:
            await users_col.update_one({"user_id": target_id}, {"$set": {"work_approved": True}, "$inc": {"balance": amount}})
            
            async def notify_user():
                notify_text = f"🎉 **Work Accepted!**\n\nYour recent work submission was approved. You can now request next work.\n💰 **Balance Added:** ₹{amount}"
                try:
                    await bot.send_message(target_id, notify_text)
                except Exception as e:
                    logger.error(f"Could not notify user {target_id}: {e}")
            asyncio.create_task(notify_user())
            
        await state.clear()
        
        pending_left = await submissions_col.count_documents({"user_id": target_id, "status": "pending"})
        kb = InlineKeyboardBuilder()
        
        if pending_left > 0:
            kb.row(InlineKeyboardButton(text=f"Check Next ({pending_left} left) ➡️", callback_data=f"view_unmarked_{target_id}_0"))
        
        kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_unmarked_subs_0"))
        kb.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="open_admin_panel"))

        await message.reply(f"✅ Successfully marked as Accepted and added ₹{amount} to User `{target_id}`'s balance.\n\nPending remaining for this user: {pending_left}", parse_mode="Markdown", reply_markup=kb.as_markup())
        
    except Exception as e:
        logger.error(f"Error adding sub balance: {e}")
        await state.clear()

# --- UPGRADED DENY LOGIC (QA PERSONA + DENY ALL + INSTANT LIMIT OPEN + PHOTO SUPPORT) ---
@router.callback_query(F.data.startswith("deny_sub_"))
async def admin_deny_sub(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer("Enter denial reason.") 
        sub_id = callback.data.split("_")[-1]
        sub = await submissions_col.find_one({"_id": ObjectId(sub_id)})
        
        if not sub or sub.get("status") != "pending":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_unmarked_subs_0")]])
            await safe_edit_message(callback, "⚠️ Submission already processed or not found.", kb)
            return
            
        user_id = sub["user_id"]
        
        await state.set_state(AdminStates.waiting_for_deny_reason)
        await state.update_data(target_user_id=user_id, target_sub_id=sub_id)
        
        prompt_text = "\n\n❌ **STATUS: DENYING ALL PENDING WORK**\n\n👉 **Please type the reason OR send a Photo with caption for denying this user's ALL pending work:**"
        
        try:
            if callback.message.caption:
                await callback.message.edit_caption(
                    caption=callback.message.caption + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
            else:
                await callback.message.edit_text(
                    text=callback.message.text + prompt_text,
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel & Back", callback_data=f"view_unmarked_{user_id}_0")]])
                )
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error in deny_sub: {e}")

@router.message(AdminStates.waiting_for_deny_reason)
async def process_deny_reason(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        # Support for both Text and Photo with Caption
        reason_text = message.caption if message.photo else message.text
        reason = reason_text.strip() if reason_text else "No specific reason provided."
        photo_id = message.photo[-1].file_id if message.photo else None
        
        data = await state.get_data()
        target_id = data.get("target_user_id")
        
        if target_id:
            # UPGRADED: Deny ALL pending submissions for this user
            await submissions_col.update_many(
                {"user_id": target_id, "status": "pending"},
                {"$set": {"status": "denied", "deny_reason": reason}}
            )
            
            # UPGRADED: Instantly open work limit
            await users_col.update_one({"user_id": target_id}, {"$set": {"work_approved": True}})
            
            async def deny_bg():
                try:
                    # FEATURE 5: QUALITY CHECK LANGUAGE
                    deny_msg = f"❌ **Work Rejected by [Quality Assurance Team]**\n\nYour recent submission did not pass our quality checks.\n📝 **Reason:** {reason}\n\nPlease ensure your post views are clearly visible and resubmit immediately to avoid account penalty."
                    if photo_id:
                        await bot.send_photo(target_id, photo=photo_id, caption=deny_msg)
                    else:
                        await bot.send_message(target_id, deny_msg)
                except Exception as e:
                    logger.error(f"Could not notify user {target_id}: {e}")
            asyncio.create_task(deny_bg())
            
        await state.clear()
        
        pending_left = await submissions_col.count_documents({"user_id": target_id, "status": "pending"})
        kb = InlineKeyboardBuilder()
        
        if pending_left > 0:
            kb.row(InlineKeyboardButton(text=f"Check Next ({pending_left} left) ➡️", callback_data=f"view_unmarked_{target_id}_0"))
            
        kb.row(InlineKeyboardButton(text="« Back to List", callback_data="admin_unmarked_subs_0"))
        kb.row(InlineKeyboardButton(text="🏠 Main Menu", callback_data="open_admin_panel"))

        await message.reply(f"✅ **ALL** pending submissions marked as DENIED for User `{target_id}`.\nInstant limit opened.\n\nPending remaining for this user: {pending_left}", parse_mode="Markdown", reply_markup=kb.as_markup())
        
    except Exception as e:
        logger.error(f"Error denying sub: {e}")
        await state.clear()

# --- MANAGE USERS, REMOVE USER, BAN USER ---
@router.callback_query(F.data == "admin_add_user_panel")
async def admin_add_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_add_user)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        text = (
            "➕ **Add / Approve User**\n\n"
            "Send the user's details to activate their account.\n"
            "Supported formats:\n"
            "• `123456789` (Telegram ID)\n"
            "• `@username` or `username`\n"
            "• **Forward any message from that user here**\n\n"
            "*Note: If they haven't started the bot yet, they will be pre-approved!*"
        )
        await safe_edit_message(callback, text, cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_add_user_prompt: {e}")

@router.message(AdminStates.waiting_for_add_user)
async def admin_add_user_save(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        user_id = None
        username = ""
        name = ""
        query = ""
        
        if message.forward_origin:
            if message.forward_origin.type == "user":
                user_id = message.forward_origin.sender_user.id
                username = message.forward_origin.sender_user.username or ""
                name = message.forward_origin.sender_user.first_name or "User"
                query = str(user_id)
            elif message.forward_origin.type == "hidden_user":
                await message.reply("⚠️ This user has hidden their account privacy for forwarded messages. Please add them using their Chat ID or Username instead.", reply_markup=await get_admin_panel_keyboard())
                await state.clear()
                return
            else:
                await message.reply("⚠️ Cannot extract user from this forwarded message. Ensure it's forwarded from a normal user.", reply_markup=await get_admin_panel_keyboard())
                await state.clear()
                return
        else:
            query = message.text.strip() if message.text else ""
            if not query:
                await message.reply("⚠️ Please send text or forward a message.")
                return
                
            if "t.me/" in query:
                query = query.split("t.me/")[-1].strip()
            elif query.startswith("@"):
                query = query[1:].strip()
                
        is_digit = query.lstrip('-').isdigit() if query else False
        
        user = None
        if is_digit:
            user = await users_col.find_one({"user_id": int(query)})
        else:
            user = await users_col.find_one({"username": {"$regex": f"^{query}$", "$options": "i"}})
            
        if user:
            final_name = user.get("first_name", query)
            await message.reply(f"✅ User **{clean_md(final_name)}** is now an ACTIVE member! (Processing in bg)", reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
            
            async def update_existing_user():
                await users_col.update_one(
                    {"_id": user["_id"]}, 
                    {"$set": {"is_active": True, "is_banned": False, "approval_date": datetime.now()}}
                )
                try:
                    await bot.send_message(user["user_id"], "🎉 **You have successfully applied and we have successfully approved you for our staff joining!**\n\nPlease use /start, go on **Staff Only** and submit your work.", parse_mode="Markdown")
                except Exception:
                    pass
            asyncio.create_task(update_existing_user())
        else:
            new_user_id = user_id if user_id else (int(query) if is_digit else 0)
            new_username = username if username else (query if not is_digit else "")
            new_name = name if name else query
            
            success_msg = f"✅ User `{clean_md(query)}` has been **pre-approved** and added to Active Members!\n(Processing in background)"
            await message.reply(success_msg, reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
            
            async def insert_new_user():
                await users_col.insert_one({
                    "user_id": new_user_id,
                    "username": new_username,
                    "first_name": new_name,
                    "is_active": True,
                    "is_banned": False,
                    "emp_id": f"EMP-{random.randint(10000, 99999)}",
                    "tc_accepted": False,
                    "approval_date": datetime.now(),
                    "balance": 0,
                    "submission_count": 0,
                    "join_date": datetime.now(),
                    "schedule_step": 0,
                    "sent_batches": [],
                    "pending_second_batch": False, 
                    "work_approved": True, 
                    "last_work_time": None,
                    "notified_new_work": False,
                    "has_submitted_current_work": True,
                    "notified_missed_4h": False,
                    "notified_missed_6h": False,
                    "notified_missed_8h": False
                })
                if new_user_id != 0:
                    try:
                        await bot.send_message(new_user_id, "🎉 **You have successfully applied and we have successfully approved you for our staff joining!**\n\nPlease use /start, go on **Staff Only** and submit your work.", parse_mode="Markdown")
                    except Exception:
                        pass
            asyncio.create_task(insert_new_user())
            
        await state.clear()
    except Exception as e:
        logger.error(f"Error in admin_add_user_save: {e}")
        await message.reply("⚠️ Error adding user. Check format or ensure the message was correctly forwarded.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()

@router.callback_query(F.data == "admin_check_user")
async def admin_check_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_user_query)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        await safe_edit_message(callback, "🔍 **Check User**\n\nPlease send the User ID, @username, or First Name of the user:", cancel_kb)
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
            await message.reply(f"⚠️ No user found for `{clean_md(query)}`.", reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
            await state.clear()
            return
            
        for u in users:
            join_date = u.get("join_date", datetime.now()).strftime("%Y-%m-%d")
            status = "✅ Active" if u.get("is_active") else ("🚫 Banned" if u.get("is_banned") else "⚪ Inactive")
            text = (
                f"👤 **User Info:**\n\n"
                f"**Name:** {clean_md(u.get('first_name'))}\n"
                f"**Username:** @{clean_md(u.get('username', 'N/A'))}\n"
                f"**ID:** `{u.get('user_id')}`\n"
                f"**Status:** {status}\n"
                f"**Balance:** ₹{u.get('balance', 0)}\n"
                f"**Total Submissions:** {u.get('submission_count', 0)}\n"
                f"**Joined:** {join_date}"
            )
            await message.reply(text, parse_mode="Markdown")
            
        await message.answer("Select another action:", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error in admin_check_user_result: {e}")

@router.callback_query(F.data == "admin_manage_admins")
async def admin_manage_admins_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_add_admin)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        text = (
            "👑 **Manage Admins**\n\n"
            "Please send the **Telegram User ID** of the person you want to make an Admin:\n\n"
            "*(This person will have full access to the admin panel)*"
        )
        await safe_edit_message(callback, text, cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_manage_admins_prompt: {e}")

@router.message(AdminStates.waiting_for_add_admin)
async def admin_manage_admins_save(message: Message, state: FSMContext) -> None:
    try:
        new_admin_id = int(message.text.strip())
        await message.reply(f"✅ User ID `{new_admin_id}` has been successfully added as an Admin!", reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
        await state.clear()
        
        async def add_admin_bg():
            await settings_col.update_one(
                {"_id": "admins"},
                {"$addToSet": {"admin_list": new_admin_id}},
                upsert=True
            )
        asyncio.create_task(add_admin_bg())
        
    except ValueError:
        await message.reply("⚠️ Please enter a valid numerical User ID.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        await message.reply("⚠️ Error adding admin. Check logs.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()

@router.callback_query(F.data.startswith("admin_currently_users_"))
async def admin_currently_users(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        ITEMS_PER_PAGE = 20
        skip_count = page * ITEMS_PER_PAGE
        
        total_users = await users_col.count_documents({"is_active": True})
        real_users = await users_col.find({"is_active": True}).skip(skip_count).limit(ITEMS_PER_PAGE).to_list(length=ITEMS_PER_PAGE)
        
        if not real_users and page == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
            await safe_edit_message(callback, "⚠️ No active assigned users found.", kb)
            return
            
        kb = InlineKeyboardBuilder()
        for u in real_users:
            name = u.get("first_name", "User")
            uid = u.get("user_id")
            kb.button(text=f"👤 {name}", callback_data=f"manage_user_{uid}")
        
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"admin_currently_users_{page-1}"))
        if skip_count + ITEMS_PER_PAGE < total_users:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_currently_users_{page+1}"))
            
        if nav_row:
            kb.row(*nav_row)
            
        kb.row(InlineKeyboardButton(text="« Back", callback_data="admin_cancel"))
        kb.adjust(2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1) 
        
        text = f"👥 **Currently Assigned Users (Page {page+1})**\nTotal Assigned: {total_users}\n\nSelect a user below to view their work profile and manage balance:"
        await safe_edit_message(callback, text, kb.as_markup())
    except Exception as e:
        logger.error(f"Error in admin_currently_users: {e}")

@router.callback_query(F.data.startswith("manage_user_"))
async def admin_manage_specific_user(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        uid = int(callback.data.split("_")[-1])
        u = await users_col.find_one({"user_id": uid})
        if not u:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_currently_users_0")]])
            await safe_edit_message(callback, "⚠️ User not found.", kb)
            return
            
        subs_count = u.get('submission_count', 0)
        balance = u.get('balance', 0)
        
        # Securing markdown names to fix active user panel crash
        name_clean = clean_md(u.get("first_name", "User"))
        
        subs_cursor = submissions_col.find({"user_id": uid}).sort("timestamp", -1).limit(2)
        recent_subs = await subs_cursor.to_list(length=2)
        
        link_text = "None"
        last_sub_name = "None"
        
        if recent_subs:
            # Fixing markdown crash for the name submitted
            last_sub_name = clean_md(str(recent_subs[0].get("user_name", u.get("first_name"))))
            link_text = ""
            for s in recent_subs:
                # Fixing markdown crash for submitted links containing underscores
                l1 = clean_md(str(s.get('link1', s.get('link', 'N/A'))))
                l2 = clean_md(str(s.get('link2', 'N/A')))
                ts = s.get('timestamp', datetime.now()).strftime("%d %b, %I:%M %p")
                link_text += f"\n🔹 [{ts}]\n   ├ {l1}\n   └ {l2}"
                
        step = u.get("schedule_step", 0)
        work_approved = u.get("work_approved", True)
        limit_status = "🟢 Available/Open" if work_approved else "🔴 Limit Hit (Waiting for Admin Approval)"
        
        # Markdown is safely constructed with clean_md() to fix crashes
        text = (
            f"👤 **User Profile:** {name_clean}\n"
            f"🆔 **ID:** `{uid}`\n"
            f"💰 **Current Balance:** ₹{balance}\n"
            f"📥 **Total Work Submissions:** {subs_count}\n"
            f"📊 **User Limit Status:** {limit_status}\n"
            f"📝 **Last Work Submitted by:** {last_sub_name}\n"
            f"🔗 **Last 2 Work Links:** {link_text}\n"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Add Balance", callback_data=f"addbal_{uid}"),
                InlineKeyboardButton(text="➖ Remove Balance", callback_data=f"rembal_{uid}")
            ],
            [
                InlineKeyboardButton(text="🔄 Update Balance", callback_data=f"updbal_{uid}"),
                InlineKeyboardButton(text="🔓 Open Limit", callback_data=f"openlimit_{uid}")
            ],
            [
                InlineKeyboardButton(text="✉️ Send Message", callback_data=f"msguser_{uid}"),
                InlineKeyboardButton(text="🗑️ Remove User", callback_data=f"rmuser_{uid}")
            ],
            [
                InlineKeyboardButton(text="🚫 Ban Permanent", callback_data=f"banuser_{uid}"),
                InlineKeyboardButton(text="« Back", callback_data="admin_currently_users_0")
            ]
        ])
        
        await safe_edit_message(callback, text, kb)
    except Exception as e:
        logger.error(f"Error in manage_user: {e}")

@router.callback_query(F.data.startswith("openlimit_"))
async def admin_open_limit(callback: CallbackQuery, bot: Bot) -> None:
    try:
        uid = int(callback.data.split("_")[-1])
        await users_col.update_one(
            {"user_id": uid}, 
            {"$set": {
                "work_approved": True, 
                "schedule_step": 0, 
                "last_work_time": None, 
                "has_submitted_current_work": True,
                "pending_second_batch": False
            }}
        )
        await callback.answer("✅ User limit successfully opened! They can take new work now.", show_alert=True)
        
        try:
            await bot.send_message(uid, "🔓 **Good News!**\n\nYour work limit has been manually opened by the Admin. You can now request your next batch of work from the Staff Dashboard.")
        except Exception:
            pass
        
        # Refresh the profile view
        callback.data = f"manage_user_{uid}"
        await admin_manage_specific_user(callback)
    except Exception as e:
        logger.error(f"Error opening limit: {e}")
        await callback.answer("⚠️ Error opening limit.", show_alert=True)

@router.callback_query(F.data.startswith("rmuser_"))
async def admin_remove_user(callback: CallbackQuery) -> None:
    try:
        uid = int(callback.data.split("_")[-1])
        await users_col.update_one({"user_id": uid}, {"$set": {"is_active": False}})
        await callback.answer("✅ User successfully removed from active staff!", show_alert=True)
        # Using mock callback data to jump back to page 0
        callback.data = "admin_currently_users_0"
        await admin_currently_users(callback)
    except Exception as e:
        logger.error(f"Error removing user: {e}")

@router.callback_query(F.data.startswith("banuser_"))
async def admin_ban_user(callback: CallbackQuery) -> None:
    try:
        uid = int(callback.data.split("_")[-1])
        await users_col.update_one({"user_id": uid}, {"$set": {"is_banned": True, "is_active": False}})
        await callback.answer("🚫 User banned permanently!", show_alert=True)
        callback.data = "admin_currently_users_0"
        await admin_currently_users(callback)
    except Exception as e:
        logger.error(f"Error banning user: {e}")

@router.callback_query(F.data.startswith("addbal_"))
async def prompt_add_bal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_add_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await safe_edit_message(callback, "👉 Enter the numerical amount to ADD to this user's balance:", kb)

@router.callback_query(F.data.startswith("rembal_"))
async def prompt_rem_bal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_remove_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await safe_edit_message(callback, "👉 Enter the numerical amount to REMOVE from this user's balance:", kb)

@router.callback_query(F.data.startswith("updbal_"))
async def prompt_upd_bal(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_update_balance_amount)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await safe_edit_message(callback, "👉 Enter the NEW exact balance amount to OVERRIDE for this user:", kb)

@router.message(AdminStates.waiting_for_add_balance_amount)
async def execute_add_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await message.reply(f"✅ ₹{amount} added to user `{uid}`.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
        async def add_bg():
            await users_col.update_one({"user_id": uid}, {"$inc": {"balance": amount}})
            if uid:
                try:
                    await bot.send_message(uid, f"🔔 **Balance Update!**\n\n✅ ₹{amount} has been added to your wallet by System.")
                except Exception as e:
                    logger.error(f"Could not notify user {uid}: {e}")
        asyncio.create_task(add_bg())
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

@router.message(AdminStates.waiting_for_remove_balance_amount)
async def execute_rem_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await message.reply(f"✅ ₹{amount} removed from user `{uid}`.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
        async def rem_bg():
            await users_col.update_one({"user_id": uid}, {"$inc": {"balance": -amount}})
            if uid:
                try:
                    await bot.send_message(uid, f"🔔 **Balance Update!**\n\n⚠️ ₹{amount} has been deducted from your wallet by System.")
                except Exception as e:
                    logger.error(f"Could not notify user {uid}: {e}")
        asyncio.create_task(rem_bg())
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

@router.message(AdminStates.waiting_for_update_balance_amount)
async def execute_upd_bal(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await message.reply(f"✅ Balance of user `{uid}` updated successfully to ₹{amount}.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
        async def upd_bg():
            await users_col.update_one({"user_id": uid}, {"$set": {"balance": amount}})
            if uid:
                try:
                    await bot.send_message(uid, f"🔔 **Balance Update!**\n\n✅ Your balance has been updated to ₹{amount} by System.")
                except Exception as e:
                    logger.error(f"Could not notify user {uid}: {e}")
        asyncio.create_task(upd_bg())
    except ValueError:
        await message.reply("⚠️ Invalid format. Please send numbers only.")

@router.callback_query(F.data.startswith("msguser_"))
async def prompt_msg_user(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    uid = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.waiting_for_single_msg)
    await state.update_data(target_user_id=uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data=f"manage_user_{uid}")]])
    await safe_edit_message(callback, "👉 Send the message you want to send to this specific user (Text, Photo, Video, etc.):", kb)

@router.message(AdminStates.waiting_for_single_msg)
async def execute_msg_user(message: Message, state: FSMContext, bot: Bot) -> None:
    try:
        data = await state.get_data()
        uid = data.get("target_user_id")
        
        await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
        await message.reply(f"✅ Message sent successfully to User ID `{uid}`!", reply_markup=await get_admin_panel_keyboard(), parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error sending message to user: {e}")
        await message.reply("⚠️ Failed to send message. User might have blocked the bot.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()

async def get_broadcast_ui(page: int, selected_ids: list) -> InlineKeyboardMarkup:
    users = await users_col.find({"is_active": True}).sort("join_date", -1).skip(page*40).limit(40).to_list(40)
    total_users = await users_col.count_documents({"is_active": True})
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
        InlineKeyboardButton(text="🌍 Broadcast to ACTIVE", callback_data="bcast_send_all")
    )
    kb.row(InlineKeyboardButton(text="« Back", callback_data="open_admin_panel"))
    
    return kb.as_markup()

@router.callback_query(F.data == "admin_broadcast_menu")
async def bcast_menu_start(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.update_data(bcast_selected_ids=[])
        kb = await get_broadcast_ui(0, [])
        await safe_edit_message(callback, "📢 **Broadcast Menu (ACTIVE MEMBERS ONLY)**\n\nSelect active users to send a message to, or broadcast to everyone:", kb)
    except Exception as e:
        logger.error(f"Error starting broadcast menu: {e}")

@router.callback_query(F.data.startswith("bcast_page_"))
async def bcast_page_change(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        data = await state.get_data()
        selected = data.get("bcast_selected_ids", [])
        kb = await get_broadcast_ui(page, selected)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error changing broadcast page: {e}")

@router.callback_query(F.data.startswith("bcast_tgl_"))
async def bcast_toggle_user(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
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
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except TelegramBadRequest:
            pass
    except Exception as e:
        logger.error(f"Error toggling broadcast user: {e}")

@router.callback_query(F.data.in_(["bcast_send_selected", "bcast_send_all"]))
async def bcast_prepare_send(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        mode = "all" if callback.data == "bcast_send_all" else "selected"
        data = await state.get_data()
        selected = data.get("bcast_selected_ids", [])
        
        if mode == "selected" and not selected:
            await callback.answer("⚠️ Please select at least one user first!", show_alert=True)
            return
            
        await state.set_state(AdminStates.waiting_for_broadcast_msg)
        await state.update_data(bcast_mode=mode)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_broadcast_menu")]])
        text = f"👉 Send the message you want to broadcast to **{mode.upper()} ACTIVE** users:\n\n*(You can send text, photo, video, etc.)*"
        await safe_edit_message(callback, text, kb)
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
            users = await users_col.find({"is_active": True}).to_list(None)
            targets = [u["user_id"] for u in users]
        else:
            targets = selected
            
        processing_msg = await message.reply(f"⏳ Broadcasting to {len(targets)} ACTIVE users...")
        sent_count = 0
        
        for uid in targets:
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id)
                sent_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                pass
                
        await processing_msg.delete()
        await message.reply(f"✅ Broadcast complete! Successfully sent to {sent_count} ACTIVE users.", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
    except Exception as e:
        logger.error(f"Error sending broadcast: {e}")
        await state.clear()

# --- OPTIMIZED: BALANCE INQUIRY ---
@router.callback_query(F.data.startswith("admin_balance_inquiry_"))
async def admin_balance_inquiry_handler(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        page = int(callback.data.split("_")[-1])
        ITEMS_PER_PAGE = 15
        skip_count = page * ITEMS_PER_PAGE
        
        # UPGRADED: Filter exactly for active users only
        total_users = await users_col.count_documents({"is_active": True}) 
        
        # UPGRADED: Ensure find() query strictly matches is_active=True
        users = await users_col.find(
            {"is_active": True}, 
            projection={"first_name": 1, "join_date": 1, "balance": 1, "submission_count": 1}
        ).sort("join_date", -1).skip(skip_count).limit(ITEMS_PER_PAGE).to_list(length=ITEMS_PER_PAGE)
        
        if not users and page == 0:
            await safe_edit_message(callback, "⚠️ No active members found.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]]))
            return
            
        text = f"💰 **Active Members Balance Inquiry (Page {page+1})**\n\n"
        
        for u in users:
            name = str(u.get("first_name", "User"))
            if len(name) > 15: name = name[:12] + "..."
            
            jd = u.get("join_date", datetime.now())
            day_str = str(jd.day)
            bal = u.get("balance", 0)
            subs_count = u.get("submission_count", 0)
            
            link_logo = " 🔗 " if subs_count > 0 else " "
            
            # clean_md implemented here to fix crashes
            text += f"👤 {clean_md(name)} | 📅 {day_str}{link_logo}₹{bal}\n"
            
        kb = InlineKeyboardBuilder()
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"admin_balance_inquiry_{page-1}"))
        if skip_count + ITEMS_PER_PAGE < total_users:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_balance_inquiry_{page+1}"))
            
        if nav_row:
            kb.row(*nav_row)
        kb.row(InlineKeyboardButton(text="« Back", callback_data="open_admin_panel"))
        
        await safe_edit_message(callback, text, kb.as_markup())
    except Exception as e:
        logger.error(f"Error in balance inquiry: {e}")

@router.callback_query(F.data.startswith("admin_work_links_"))
async def admin_all_work_links(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
        parts = callback.data.split("_")
        page = 0
        if len(parts) > 3 and parts[3].isdigit():
            page = int(parts[3])
            
        page_size = 5
        skip_count = page * page_size
        
        pipeline = [
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": "$user_id",
                "user_name": {"$first": "$user_name"},
                "links": {"$push": {"l1": "$link1", "l2": "$link2", "ts": "$timestamp"}},
                "latest": {"$first": "$timestamp"}
            }},
            {"$sort": {"latest": -1}},
            {"$facet": {
                "metadata": [{"$count": "total_users"}],
                "data": [{"$skip": skip_count}, {"$limit": page_size}]
            }}
        ]
        
        result = await submissions_col.aggregate(pipeline).to_list(length=1)
        
        total_users_with_links = 0
        if result and result[0]["metadata"]:
            total_users_with_links = result[0]["metadata"][0]["total_users"]
            
        users_data = result[0]["data"] if result else []
        
        pipeline_count = [
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": "$user_id",
                "links": {"$push": "$_id"}
            }},
            {"$project": {"link_count": {"$size": {"$slice": ["$links", 2]}}}}
        ]
        count_result = await submissions_col.aggregate(pipeline_count).to_list(length=None)
        total_active_links = sum(item["link_count"] for item in count_result)
        
        if not users_data and page == 0:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="open_admin_panel")]])
            await safe_edit_message(callback, "✅ No links found.", kb)
            return
            
        text = "🔗 **User Work Links (Latest 2 Links Per User)**\n\n"
        text += f"📊 **Total Active Links:** {total_active_links}\n\n"
        
        for s in users_data:
            name = s.get('user_name', 'Unknown')
            user_links = s.get('links', [])[:2]
            
            # clean_md fixes crashes for Markdown issues
            text += f"👤 **{clean_md(name)}**\n"
            for link_data in user_links:
                l1 = clean_md(str(link_data.get('l1', link_data.get('link', 'N/A'))))
                l2 = clean_md(str(link_data.get('l2', 'N/A')))
                ts_val = link_data.get('ts')
                ts = ts_val.strftime("%d %b, %I:%M %p") if isinstance(ts_val, datetime) else "N/A"
                text += f"🕒 Date: {ts}\n"
                text += f"├ 🔗 {l1}\n"
                text += f"└ 🔗 {l2}\n"
            text += "\n"
            
        kb = InlineKeyboardBuilder()
        nav_row = []
        
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="⬅️ Preview", callback_data=f"admin_work_links_{page-1}"))
        if skip_count + page_size < total_users_with_links:
            nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"admin_work_links_{page+1}"))
            
        if nav_row:
            kb.row(*nav_row)
            
        kb.row(InlineKeyboardButton(text="« Back", callback_data="open_admin_panel"))
        
        try:
            await callback.message.edit_text(
                text, 
                reply_markup=kb.as_markup(), 
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        except TelegramBadRequest:
            try:
                await callback.message.edit_text(text, reply_markup=kb.as_markup(), disable_web_page_preview=True)
            except TelegramBadRequest:
                pass
            
    except Exception as e:
        logger.error(f"Error in admin_work_links: {e}")

@router.callback_query(F.data == "admin_set_work")
async def admin_set_work_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_work_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        await safe_edit_message(callback, "🔗 **Set Work Link**\n\nPlease send the new URL for the 'Apply to Work' button:", cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_set_work_prompt: {e}")

@router.message(AdminStates.waiting_for_work_link)
async def admin_set_work_save(message: Message, state: FSMContext) -> None:
    try:
        new_link = message.text.strip()
        await message.reply(f"✅ 'Apply to Work' button link updated successfully!\n\nNew Link: {new_link}", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
        async def save_work_link_bg():
            await settings_col.update_one(
                {"_id": "global_links"},
                {"$set": {"work_link": new_link}},
                upsert=True
            )
        asyncio.create_task(save_work_link_bg())
        
    except Exception as e:
        logger.error(f"Error saving work link: {e}")

@router.callback_query(F.data == "admin_set_proof")
async def admin_set_proof_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_proof_link)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        await safe_edit_message(callback, "🔗 **Set Proof Link**\n\nPlease send the new URL for the 'Updates' button:", cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_set_proof_prompt: {e}")

@router.message(AdminStates.waiting_for_proof_link)
async def admin_set_proof_save(message: Message, state: FSMContext) -> None:
    try:
        new_link = message.text.strip()
        await message.reply(f"✅ 'Updates' button link updated successfully!\n\nNew Link: {new_link}", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
        async def save_proof_link_bg():
            await settings_col.update_one(
                {"_id": "global_links"},
                {"$set": {"proof_link": new_link}},
                upsert=True
            )
        asyncio.create_task(save_proof_link_bg())
        
    except Exception as e:
        logger.error(f"Error saving proof link: {e}")

# --- FEATURE 6: NOTICE BOARD LOGIC (ADMIN SIDE) ---
@router.callback_query(F.data == "admin_set_notice")
async def admin_set_notice_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.set_state(AdminStates.waiting_for_notice)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back", callback_data="admin_cancel")]])
        await safe_edit_message(callback, "📝 **Set Notice Board**\n\nPlease send the new notice text/update to display to all staff members:", cancel_kb)
    except Exception as e:
        logger.error(f"Error in admin_set_notice_prompt: {e}")

@router.message(AdminStates.waiting_for_notice)
async def admin_set_notice_save(message: Message, state: FSMContext) -> None:
    try:
        new_notice = message.text.strip() if message.text else ""
        if not new_notice:
            await message.reply("⚠️ Please send text only for the notice board.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="admin_cancel")]]))
            return
            
        await settings_col.update_one(
            {"_id": "notice_board"},
            {"$set": {"text": new_notice}},
            upsert=True
        )
        await message.reply(f"✅ Notice Board updated successfully!\n\n**Preview:**\n{new_notice}", reply_markup=await get_admin_panel_keyboard())
        await state.clear()
        
    except Exception as e:
        logger.error(f"Error saving notice: {e}")

@router.callback_query(F.data == "admin_cancel")
async def admin_cancel_action(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.clear()
        text = "👑 **Admin Control Panel**\n\nWelcome back, Master. Select an option below to manage the bot:"
        await safe_edit_message(callback, text, await get_admin_panel_keyboard())
    except Exception as e:
        logger.error(f"Error in admin_cancel: {e}")

@router.callback_query(F.data == "admin_close")
async def admin_close_panel(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await callback.answer()
        await state.clear()
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Error closing admin panel: {e}")

# ==========================================
# SCHEDULED TASKS (NEW & MISSED WORK NOTIFICATIONS)
# ==========================================
async def work_notification_job(bot: Bot) -> None:
    """Checks for users who completed cooldowns AND triggers 4h/6h/8h missing work alerts."""
    try:
        now = datetime.now()
        # Find active, un-banned users
        users_cursor = users_col.find({"is_active": True, "is_banned": False})
        users = await users_cursor.to_list(length=None)
        
        for u in users:
            uid = u["user_id"]
            
            # --- 1. NEW WORK NOTIFICATION (Cooldown completed) ---
            if not u.get("notified_new_work", False):
                step = u.get("schedule_step", 0)
                work_approved = u.get("work_approved", True)
                approval_date = u.get("approval_date")
                
                if not approval_date:
                    approval_date = u.get("join_date", now)
                    
                last_work_time = u.get("last_work_time")
                next_allowed = None
                
                if step == 0:
                    next_allowed = approval_date + timedelta(hours=4)
                elif step == 1:
                    # Upgrade: Notify bas time poora hone pe
                    next_allowed = last_work_time + timedelta(hours=6) if last_work_time else now + timedelta(hours=6)
                else:
                    next_allowed = last_work_time + timedelta(hours=8) if last_work_time else now + timedelta(hours=8)
                
                if next_allowed and now >= next_allowed:
                    try:
                        # UPGRADED: Added Click here to download inline button
                        dl_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📥 Click here to download", callback_data="request_new_work")]])
                        
                        # FEATURE 1: FORMALIZED NEW BATCH MESSAGE
                        await bot.send_message(
                            uid, 
                            "🔔 **New Batch Assigned [Operations Team]**\n\nDear Employee, your cooldown period has ended. A new batch of tasks has been credited to your account. Please visit the 'Staff Only' dashboard to download and begin your work.",
                            reply_markup=dl_kb
                        )
                        await users_col.update_one({"_id": u["_id"]}, {"$set": {"notified_new_work": True}})
                    except Exception as e:
                        logger.error(f"Failed to notify new work to user {uid}: {e}")

            # --- 2. MISSED WORK NOTIFICATIONS (4h, 6h, 8h) ---
            has_submitted = u.get("has_submitted_current_work", True)
            if not has_submitted and u.get("last_work_time"):
                last_time = u.get("last_work_time")
                diff_hours = (now - last_time).total_seconds() / 3600
                
                notified_4h = u.get("notified_missed_4h", False)
                notified_6h = u.get("notified_missed_6h", False)
                notified_8h = u.get("notified_missed_8h", False)
                
                updates = {}
                msg = None
                
                # FEATURE 3: ADDED DEPARTMENT PERSONAS TO MISSED ALERTS
                if diff_hours >= 8 and not notified_8h:
                    msg = "⚠️ **Alert: 8 Hours Passed! [Operations Manager]**\n\nWe are noticing you are offline. Please go in the staff section, click on 'New Work', complete your work and submit work.\n\nPlease clear with me if you are interested, otherwise we will clear your payment and restrict your account."
                    updates = {"notified_missed_8h": True, "notified_missed_6h": True, "notified_missed_4h": True}
                elif diff_hours >= 6 and not notified_6h:
                    msg = "⚠️ **Alert: 6 Hours Passed! [Operations Team]**\n\nAapko work assign hue 6 ghante ho gaye hain. Please submit your work soon!"
                    updates = {"notified_missed_6h": True, "notified_missed_4h": True}
                elif diff_hours >= 4 and not notified_4h:
                    msg = "⚠️ **Alert: 4 Hours Passed! [Operations Team]**\n\nAapko work assign hue 4 ghante ho chuke hain. Don't forget to submit your work."
                    updates = {"notified_missed_4h": True}
                    
                if msg:
                    try:
                        await bot.send_message(uid, msg, parse_mode="Markdown")
                        await users_col.update_one({"_id": u["_id"]}, {"$set": updates})
                    except Exception as e:
                        logger.error(f"Failed to send missed work alert to {uid}: {e}")

    except Exception as e:
        logger.error(f"Error in work_notification_job: {e}")

# --- AUTO BROADCAST JOB FOR FAKE PAYOUTS ---
async def payout_broadcast_job(bot: Bot) -> None:
    """Checks for newly generated fake payouts in the last 5 minutes and broadcasts them."""
    try:
        now = datetime.now()
        start_window = (now - timedelta(minutes=5)).time()
        end_window = now.time()
        
        withdrawals, _, _ = await get_daily_withdrawals()
        
        to_broadcast = []
        for w in withdrawals:
            w_time = w["time_obj"]
            # Check if this fake payout's time falls in the last 5 minutes
            if start_window <= w_time <= end_window:
                to_broadcast.append(w)
                
        if not to_broadcast:
            return
            
        active_users = await users_col.find({"is_active": True, "is_banned": False}).to_list(length=None)
        
        for w in to_broadcast:
            name = w["name"]
            emp_id = w["emp_id"]
            amount_str = w["amount_str"]
            is_crypto = w["is_crypto"]
            
            # FEATURE 2 & 3: FORMAL PAYOUT MSG WITH EMP_ID, UTR/TXN AND FINANCE TEAM
            msg = (
                f"🎉 **New Withdrawal Update [Finance & Billing Dept.]**\n\n"
                f"👤 **Name:** {name}\n"
                f"🆔 **EMP ID:** `{emp_id}`\n"
                f"💰 **Amount:** {amount_str}\n"
            )
            
            if is_crypto:
                msg += f"🔗 **TxN Hash:** `{w['txn_hash']}`\n\n"
            else:
                msg += f"🏦 **UTR No:** `{w['utr']}`\n\n"
                
            msg += "✅ Your withdrawal is successful. If any issue, so please contact our admin."
                
            for u in active_users:
                try:
                    await bot.send_message(u["user_id"], msg)
                    await asyncio.sleep(0.05) # Rate limit protection
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"Error in payout_broadcast_job: {e}")


# ==========================================
# MAIN EXECUTION
# ==========================================

async def main() -> None:
    logger.info("Starting Bot...")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    # Scheduler Setup for the Notification Background Loop (Runs every 5 minutes)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(work_notification_job, 'interval', minutes=5, args=[bot])
    scheduler.add_job(payout_broadcast_job, 'interval', minutes=5, args=[bot]) # BROADCAST JOB
    scheduler.start()
    
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
