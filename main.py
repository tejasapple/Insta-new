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
# FAKE DATA & LOGIC
# ==========================================

# Names are now fully mixed naturally for a professional look across all months.
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

# Total 90 names divided optimally, with exactly 12 in September
FAKE_MEMBERS_BY_MONTH = {
    "April 2026": FAKE_NAMES[0:20],       
    "May 2026": FAKE_NAMES[20:40],        
    "June 2026": FAKE_NAMES[40:59],       
    "July 2026": FAKE_NAMES[59:78],       
    "September 2026": FAKE_NAMES[78:90]  
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
        # Check if pre-registered via ID
        existing_by_id = await users_col.find_one({"user_id": user_id})
        if existing_by_id:
            # If user was added by admin using ID, their first_name is stored as their ID temporarily.
            if existing_by_id.get("first_name") == str(user_id) or not existing_by_id.get("username"):
                await users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"username": username, "first_name": first_name}}
                )
            return

        # Check if pre-registered via Username / Link
        existing_by_username = None
        if username:
            existing_by_username = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
        
        if existing_by_username and existing_by_username.get("user_id") == 0:
            await users_col.update_one(
                {"_id": existing_by_username["_id"]},
                {"$set": {"user_id": user_id, "first_name": first_name}}
            )
            return

        # Standard new user registration
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
    waiting_for_link = State()
    waiting_for_photo = State()

class AdminStates(StatesGroup):
    waiting_for_work_link = State()
    waiting_for_proof_link = State()
    waiting_for_user_query = State()
    waiting_for_add_user = State()

# ==========================================
# KEYBOARDS
# ==========================================

def get_main_menu_keyboard(work_link: str, proof_link: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    # URL Sanitization logic to PREVENT CRASHES if admin sets an invalid link like "@username"
    def sanitize_url(url: str) -> str:
        url = url.strip()
        if url.startswith("@"):
            return f"https://t.me/{url[1:]}"
        if not url.startswith("http://") and not url.startswith("https://"):
            return f"https://{url}"
        return url

    kb = [
        [
            InlineKeyboardButton(text="💸 Approved Withdrawals", callback_data="withdrawal_list")
        ],
        [
            InlineKeyboardButton(text="💳 Request Withdrawal", callback_data="request_withdraw")
        ],
        [
            InlineKeyboardButton(text="👥 Active Members", callback_data="active_members"),
            InlineKeyboardButton(text="💰 My Balance", callback_data="my_balance")
        ],
        [
            InlineKeyboardButton(text="🟢 Apply to Work", callback_data="apply_work"),
            InlineKeyboardButton(text="📝 Submit Work", callback_data="submit_work")
        ],
        [
            InlineKeyboardButton(text="🚀 Start Work Now", url=sanitize_url(work_link))
        ],
        [
            InlineKeyboardButton(text="🧾 Payment Screenshot Proof", url=sanitize_url(proof_link))
        ]
    ]
    
    # Show Admin Panel button if the user is the Admin
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
        user_id = message.from_user.id
        
        # Check existing user logic before registration for notification purpose
        existing_by_id = await users_col.find_one({"user_id": user_id})
        is_pre_registered = False
        
        if not existing_by_id and username:
            existing_by_user = await users_col.find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
            if existing_by_user and existing_by_user.get("user_id") == 0:
                is_pre_registered = True

        await register_user_if_not_exists(user_id, username, first_name)
        
        # Notify admin for completely new users
        if not existing_by_id and not is_pre_registered and ADMIN_ID != 0:
            notify_text = f"🆕 **New User Started the Bot!**\n\n👤 Name: {first_name}\n🔗 Username: @{username}\n🆔 ID: `{user_id}`"
            await bot.send_message(ADMIN_ID, notify_text, parse_mode="Markdown")

        settings = await get_bot_settings()
        is_admin = (user_id == ADMIN_ID)
        
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
        real_users = await real_users_cursor.to_list(length=500)
        
        text = "🌟 **Our Active Working Members** 🌟\n\n"
        
        for month, names in FAKE_MEMBERS_BY_MONTH.items():
            if month == "September 2026":
                total_sept = len(names) + len(real_users)
                text += f"📅 **{month} (Total: {total_sept} Members)**\n"
                combined_names = names.copy()
                for u in real_users:
                    # Will display pre-registered names cleanly
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
        
        # Note for Admin: Notification disabled as requested. Check manually via "Pending Submissions" button.
        # if ADMIN_ID != 0:
        #     await bot.send_message(...)
            
    except Exception as e:
        logger.error(f"Error saving submission: {e}")
        await message.reply("⚠️ Failed to submit work. Please try again.")
        await state.clear()

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.clear()
        settings = await get_bot_settings()
        is_admin = (callback.from_user.id == ADMIN_ID)
        text = (
            f"Welcome {callback.from_user.first_name}!\n\n"
            "Earn money by running Instagram Ads. Choose an option below to get started or manage your work."
        )
        await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(settings["work_link"], settings["proof_link"], is_admin))
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

@router.callback_query(F.data == "open_admin_panel")
async def open_admin_panel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        if callback.from_user.id != ADMIN_ID:
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
        await callback.message.edit_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")

@router.callback_query(F.data == "admin_add_user_panel")
async def admin_add_user_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        await state.set_state(AdminStates.waiting_for_add_user)
        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel")]])
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
        
        # Clean formatting
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
            # Activate existing user
            await users_col.update_one(
                {"_id": user["_id"]}, 
                {"$set": {"is_active": True, "approval_date": datetime.now()}}
            )
            name = user.get("first_name", query)
            await message.reply(f"✅ User **{name}** is now an ACTIVE member!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        else:
            # Pre-register user so they immediately show up
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
# OLD ADMIN COMMANDS
# ==========================================

@router.message(Command("add_user"))
async def admin_add_user(message: Message) -> None:
    try:
        if message.from_user.id != ADMIN_ID:
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
