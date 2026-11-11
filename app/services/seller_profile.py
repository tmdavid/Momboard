"""Load/save the seller's company profile and keep the process-wide slot in sync."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.seller import SellerProfile, set_seller_profile
from app.services.app_settings import get_setting, set_setting

SETTING_KEY = "company_profile"


async def load_seller_profile(db: AsyncSession) -> SellerProfile:
    return SellerProfile.from_dict(await get_setting(db, SETTING_KEY))


async def refresh_seller_profile(db: AsyncSession) -> SellerProfile:
    """Read the saved profile and make it the live one (startup, and before each job)."""
    profile = await load_seller_profile(db)
    set_seller_profile(profile)
    return profile


async def save_seller_profile(db: AsyncSession, profile: SellerProfile) -> SellerProfile:
    await set_setting(db, SETTING_KEY, profile.to_dict())
    set_seller_profile(profile)
    return profile
