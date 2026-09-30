import asyncio
import logging
import html
import re
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy.ext.asyncio import AsyncSession
from bot.config import config
from bot.models.models import User, UserStatus
from bot.services.user_service import UserService
from bot.services.seller_service import SellerService
from bot.services.plan_service import PlanService
from bot.services.aadhaar_service import AadhaarService
from bot.keyboards.reply import get_main_keyboard
from bot.keyboards.inline import (
    get_payment_packages_keyboard,
    get_seller_contact_keyboard,
    get_recharge_approval_keyboard,
    get_approval_keyboard
)

logger = logging.getLogger(__name__)
router = Router()

class AadhaarStates(StatesGroup):
    waiting_for_mobile = State()
    waiting_for_name = State()

# ── Command Handlers ─────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, bot: Bot):
    user_service = UserService(session)
    user = await user_service.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name
    )

    is_admin = message.from_user.id in config.admin_ids
    if is_admin and user.status != UserStatus.APPROVED:
        user.status = UserStatus.APPROVED
        await session.commit()

    # Check and apply daily free bonus
    await user_service.check_and_apply_daily_bonus(user)
    effective_credits = UserService.get_effective_credits(user)

    seller_service = SellerService(session)
    seller_summary = await seller_service.format_sellers_summary()

    welcome_text = (
        f"👋 <b>Welcome, {html.escape(message.from_user.first_name or 'User')}!</b>\n\n"
        "⚡ <b>Fast & Automated Aadhaar Download Bot</b>\n\n"
        "📥 Download genuine, password-unlocked Aadhaar PDFs & cards directly on Telegram.\n\n"
        f"🪙 <b>Your Balance:</b> <code>{effective_credits} Credit(s)</code>\n"
        f"🛍️ <b>Authorized Sellers:</b> {seller_summary}\n\n"
        "👇 <i>Select an action below or click <b>📥 Download Aadhaar</b> to begin:</i>"
    )

    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(is_admin=is_admin),
        parse_mode="HTML"
    )

@router.message(Command("help"))
@router.message(F.text == "📖 How to use")
async def btn_how_to_use(message: Message):
    help_text = (
        "📖 <b>How To Use Aadhaar Download Bot</b>\n\n"
        "1. Click <b>📥 Download Aadhaar</b> from the menu.\n"
        "2. Send the <b>10-digit Mobile Number</b> linked to your Aadhaar.\n"
        "3. Enter the <b>Full Name</b> exactly as registered in Aadhaar.\n"
        "4. If a Captcha or OTP prompt appears, simply type it in this chat.\n"
        "5. The bot will automatically retrieve, unlock, and deliver your <b>Aadhaar PDF & HD Cards</b>!\n\n"
        "ℹ️ <i>Send /cancel at any time to abort an ongoing operation.</i>"
    )
    await message.answer(help_text, parse_mode="HTML")

@router.message(Command("status"))
@router.message(Command("profile"))
@router.message(F.text == "📊 My Account")
async def cmd_account(message: Message, session: AsyncSession):
    user_service = UserService(session)
    user = await user_service.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return await message.answer("Please send /start first.")

    is_admin = message.from_user.id in config.admin_ids
    effective_credits = UserService.get_effective_credits(user)

    status_parts = []
    if is_admin:
        status_parts.append("Unlimited (Admin 👑)")
    elif user.has_active_subscription:
        status_parts.append(f"Unlimited (Valid until {user.subscription_end.strftime('%Y-%m-%d')})")
    else:
        status_parts.append(f"🪙 {user.credits} Permanent")
        if user.bonus_credits > 0:
            status_parts.append(f"🎁 {user.bonus_credits} Daily Bonus")

    balance_display = " | ".join(status_parts)

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.telegram_user_id}"

    account_text = (
        "📊 <b>Account Profile</b>\n\n"
        f"🆔 <b>User ID:</b> <code>{user.telegram_user_id}</code>\n"
        f"👤 <b>Username:</b> @{html.escape(user.username or 'N/A')}\n"
        f"💰 <b>Available Balance:</b> <code>{balance_display}</code>\n"
        f"📥 <b>Total Downloads:</b> <code>{user.total_searches}</code>\n"
        f"👥 <b>Referrals:</b> <code>{user.referral_count} users</code>\n\n"
        f"🔗 <b>Your Referral Link:</b>\n<code>{ref_link}</code>"
    )
    await message.answer(account_text, parse_mode="HTML")

@router.message(Command("refer"))
@router.message(Command("referral"))
@router.message(F.text == "👥 Refer & Earn")
async def cmd_refer(message: Message, session: AsyncSession):
    user_service = UserService(session)
    user = await user_service.get_user_by_telegram_id(message.from_user.id)
    if not user:
        return await message.answer("Please send /start first.")

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user.telegram_user_id}"

    text = (
        "👥 <b>Refer & Earn Free Credits!</b>\n\n"
        "Invite your friends and colleagues to the bot.\n"
        "Every time a friend registers with your link, both of you earn bonus download credits!\n\n"
        f"🔗 <b>Your Invite Link:</b>\n<code>{ref_link}</code>\n\n"
        f"📈 <b>Friends Invited:</b> <code>{user.referral_count}</code>\n"
        f"🎁 <b>Credits Earned:</b> <code>{user.referral_credits_earned}</code>"
    )
    await message.answer(text, parse_mode="HTML")

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    AadhaarService.cancel_task(message.from_user.id)
    await message.answer("🛑 <b>Operation cancelled.</b>", parse_mode="HTML")

# ── Aadhaar Download Workflow ────────────────────────────────────────────────

@router.message(Command("bypass"))
@router.message(F.text == "📥 Download Aadhaar")
async def btn_download_aadhaar(message: Message, session: AsyncSession, state: FSMContext):
    user_service = UserService(session)
    user = await user_service.get_or_create_user(message.from_user.id, message.from_user.username)
    is_admin = message.from_user.id in config.admin_ids

    if not is_admin and user.status != UserStatus.APPROVED:
        return await message.answer("⏳ <b>Your account is pending admin approval.</b> Please wait for an admin to approve your access.", parse_mode="HTML")

    if not is_admin and not user.has_active_subscription:
        effective_credits = UserService.get_effective_credits(user)
        if effective_credits <= 0:
            plan_service = PlanService(session)
            plans = await plan_service.get_all_plans(active_only=True)
            seller_service = SellerService(session)
            sellers = await seller_service.get_active_sellers()
            return await message.answer(
                "⚠️ <b>Insufficient Credits!</b>\n\n"
                "You have <b>0 credits</b> remaining to download an Aadhaar.\n"
                "Please purchase credits or contact our official sellers below:",
                reply_markup=get_payment_packages_keyboard(plans, sellers=sellers),
                parse_mode="HTML"
            )

    if AadhaarService.is_task_active(message.from_user.id):
        return await message.answer("⚠️ <b>A download is already in progress for your account.</b>\nPlease wait for it to complete or send /cancel.", parse_mode="HTML")

    await state.set_state(AadhaarStates.waiting_for_mobile)
    card_text = (
        "📥 <b>STEP 1/2: Mobile Verification</b>\n\n"
        "Please enter the <b>10-digit Mobile Number</b> linked with the Aadhaar card.\n\n"
        "👉 <i>Example: <code>9876543210</code></i>\n"
        "<i>Send /cancel to abort.</i>"
    )
    await message.answer(card_text, parse_mode="HTML")

@router.message(AadhaarStates.waiting_for_mobile)
async def process_mobile_input(message: Message, state: FSMContext):
    if not message.text:
        return await message.answer("⚠️ Please send a valid mobile number.")

    digits = "".join(c for c in message.text if c.isdigit())
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if len(digits) != 10:
        return await message.answer(
            "⚠️ <b>Invalid Mobile Number!</b>\n\n"
            "Please send a valid <b>10-digit Indian Mobile Number</b>.\n"
            "<i>Send /cancel to abort.</i>",
            parse_mode="HTML"
        )

    await state.update_data(mobile=digits)
    await state.set_state(AadhaarStates.waiting_for_name)

    card_text = (
        "📥 <b>STEP 2/2: Full Name</b>\n\n"
        f"📱 <b>Mobile:</b> <code>{digits}</code>\n\n"
        "Please enter the <b>Full Name</b> exactly as it appears on the Aadhaar card.\n\n"
        "<i>Send /cancel to abort.</i>"
    )
    await message.answer(card_text, parse_mode="HTML")

@router.message(AadhaarStates.waiting_for_name)
async def process_name_input(message: Message, session: AsyncSession, state: FSMContext, bot: Bot):
    if not message.text:
        return await message.answer("⚠️ Please send text input.")

    name = message.text.strip()
    if len(name) < 2:
        return await message.answer("⚠️ Name is too short. Please send the full name.")

    data = await state.get_data()
    mobile = data.get("mobile")
    await state.clear()

    user_service = UserService(session)
    user = await user_service.get_user_by_telegram_id(message.from_user.id)
    is_admin = message.from_user.id in config.admin_ids
    has_sub = getattr(user, "has_active_subscription", False)

    deduction_info = None
    if not is_admin and not has_sub:
        ok, deduction_info = await user_service.deduct_credit(user.telegram_user_id, amount=1)
        if not ok:
            return await message.answer("⚠️ Insufficient credits. Please recharge your balance.")

    init_msg = await message.answer(
        f"🚀 <b>Initializing Aadhaar Bypass...</b>\n\n"
        f"📱 <b>Target Mobile:</b> <code>{mobile}</code>\n"
        f"👤 <b>Name:</b> <b>{html.escape(name)}</b>\n\n"
        "<i>Connecting to UIDAI / UMANG servers...</i>\n"
        "<i>If an OTP or Captcha prompt appears, type it directly into this chat!</i>",
        parse_mode="HTML"
    )

    async def _execute_job():
        success = await AadhaarService.run_download_workflow(
            bot=bot,
            chat_id=message.from_user.id,
            name=name,
            mobile=mobile,
            user_info={
                "username": message.from_user.username or "N/A",
                "first_name": message.from_user.first_name or "N/A"
            }
        )

        async with session.begin():
            if success:
                user.total_searches = (user.total_searches or 0) + 1
            elif deduction_info and not is_admin and not has_sub:
                # Auto-refund credit if download failed
                await user_service.refund_deduction(user.telegram_user_id, deduction_info)
                await message.answer("💰 <i>Your search credit has been automatically refunded due to an incomplete download.</i>", parse_mode="HTML")

    asyncio.create_task(_execute_job())

# ── Dynamic Captcha & OTP Message Interceptor ────────────────────────────────

@router.message(F.text)
async def intercept_captcha_or_otp(message: Message, state: FSMContext):
    # If the automation engine is actively waiting for Captcha or OTP input from this chat
    if AadhaarService.is_user_waiting_input(message.from_user.id):
        AadhaarService.submit_user_input(message.from_user.id, message.text)
        return

    # Or if a task is running, buffer the input
    if AadhaarService.is_task_active(message.from_user.id):
        AadhaarService.submit_user_input(message.from_user.id, message.text)
        return

# ── Recharge & Seller Handlers ───────────────────────────────────────────────

@router.message(Command("recharge"))
@router.message(F.text == "💳 Request Recharge")
async def cmd_recharge(message: Message, session: AsyncSession):
    plan_service = PlanService(session)
    plans = await plan_service.get_all_plans(active_only=True)
    seller_service = SellerService(session)
    sellers = await seller_service.get_active_sellers()
    sellers_contact_str = await seller_service.format_sellers_summary()

    text = (
        "👑 <b>Buy Credits or Unlimited Plans</b>\n\n"
        f"To purchase, please contact our authorized seller ({sellers_contact_str}).\n\n"
        "Select the package you want below to send a purchase request to the admin:"
    )
    await message.answer(text, reply_markup=get_payment_packages_keyboard(plans, sellers=sellers), parse_mode="HTML")

@router.callback_query(F.data == "request_recharge")
async def cb_request_recharge(callback: CallbackQuery, session: AsyncSession):
    plan_service = PlanService(session)
    plans = await plan_service.get_all_plans(active_only=True)
    seller_service = SellerService(session)
    sellers = await seller_service.get_active_sellers()
    sellers_contact_str = await seller_service.format_sellers_summary()

    text = (
        "👑 <b>Buy Credits or Unlimited Plans</b>\n\n"
        f"To purchase, please contact our authorized seller ({sellers_contact_str}).\n\n"
        "Select the package you want below to send a purchase request to the admin:"
    )
    await callback.message.answer(text, reply_markup=get_payment_packages_keyboard(plans, sellers=sellers), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("buy_plan_"))
async def cb_buy_plan(callback: CallbackQuery, session: AsyncSession, bot: Bot):
    plan_id = int(callback.data.split("_")[-1])
    plan_service = PlanService(session)
    plan = await plan_service.get_plan_by_id(plan_id)
    if not plan:
        return await callback.answer("Plan no longer available.", show_alert=True)

    user_service = UserService(session)
    req = await user_service.create_recharge_request(
        telegram_id=callback.from_user.id,
        amount=plan.price,
        plan_id=plan.id
    )

    seller_service = SellerService(session)
    sellers = await seller_service.get_active_sellers()
    sellers_notice = await seller_service.format_recharge_notice()
    sellers_contact_str = await seller_service.format_sellers_summary()
    contact_kb = get_seller_contact_keyboard(sellers) if sellers else None

    # Alert admins of new request
    for admin_id in config.admin_ids:
        try:
            req_kb = get_recharge_approval_keyboard(req.id)
            await bot.send_message(
                admin_id,
                f"💰 <b>New Purchase Request!</b>\n\n"
                f"👤 <b>User:</b> @{callback.from_user.username or 'N/A'} (<code>{callback.from_user.id}</code>)\n"
                f"📦 <b>Package:</b> {plan.name} (₹{plan.price})\n\n"
                "Click below to approve or reject after verifying payment:",
                reply_markup=req_kb,
                parse_mode="HTML"
            )
        except Exception:
            pass

    await callback.answer(f"✅ Request created! Please contact {sellers_contact_str} to pay.")
    await callback.message.edit_text(
        f"✅ <b>Purchase Request Sent!</b>\n\nYou selected: <b>{plan.name} (₹{plan.price})</b>\n\n"
        f"{sellers_notice}\n\n"
        "Once payment is confirmed, your account will be upgraded instantly!",
        reply_markup=contact_kb,
        parse_mode="HTML"
    )
