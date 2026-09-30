from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    
    # User buttons
    builder.button(text="📥 Download Aadhaar")
    builder.button(text="📊 My Account")
    builder.button(text="👥 Refer & Earn")
    builder.button(text="📖 How to use")
    
    if not is_admin:
        builder.button(text="💳 Request Recharge")
        
    # Admin buttons
    if is_admin:
        builder.button(text="⚙️ Manage Users")
        builder.button(text="💰 Manage Points")
        builder.button(text="📦 Manage Plans")
        builder.button(text="📢 Channels")
        builder.button(text="🛍️ Manage Sellers")
    
    # Adjust layout:
    # Row 1: Download Aadhaar (1)
    # Row 2: My Account & Refer & Earn (2)
    # Row 3: How to use & Request Recharge (2)
    # Row 4+: Admin buttons (2 each)
    if is_admin:
        builder.adjust(1, 2, 1, 2, 2, 1)
    else:
        builder.adjust(1, 2, 2)
        
    return builder.as_markup(resize_keyboard=True)
