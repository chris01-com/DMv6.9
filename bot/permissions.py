import discord
from typing import List


def has_quest_creation_permission(user: discord.Member, guild: discord.Guild) -> bool:
    """Check if user has permission to create quests"""
    # Server owner always has permission
    if guild and user.id == guild.owner_id:
        return True
    
    # Check for administrator permission
    if user.guild_permissions.administrator:
        return True
    
    # Check for manage_guild permission
    if user.guild_permissions.manage_guild:
        return True
    
    # Check for manage_channels permission
    if user.guild_permissions.manage_channels:
        return True
    
    # Check for specific quest-related roles (expanded for Heavenly Demon Sect)
    quest_creator_roles = [
        "Quest Creator",
        "Quest Master", 
        "QuestMaster",
        "Quest Admin",
        "Quest Manager",
        "Moderator",
        "Admin",
        "Staff",
        # Heavenly Demon Sect specific roles
        "Heavenly Demon",
        "Demon God", 
        "Demon Sovereign",
        "Supreme Demon",
        "Guardian",
        "Demon King",
        "Divine Demon",
        "Ancient Demon",
        "Primordial Demon",
        "Core Demon",
        "Elder Demon",
        "Inner Demon",
        "Outer Demon",
        "Demonic Commander",
        "Young Master",
        # Generic Discord roles that might exist
        "Member",
        "@everyone"  # Allow everyone to create quests by default
    ]
    
    user_roles = [role.name.lower() for role in user.roles]
    for role_name in quest_creator_roles:
        if role_name.lower() in user_roles:
            return True
    
    # If no specific roles found, allow quest creation for any guild member by default
    # This makes the bot more user-friendly for small servers
    return True


def can_manage_quest(user: discord.Member, guild: discord.Guild, quest_creator_id: int) -> bool:
    """Check if user can manage (approve/reject/delete) a quest"""
    # Quest creator can always manage their own quest
    if user.id == quest_creator_id:
        return True
    
    # Check if user has quest creation permission (admins/mods can manage all quests)
    return has_quest_creation_permission(user, guild)


def user_has_required_roles(user: discord.Member, required_role_ids: List[int]) -> bool:
    """Check if user has any of the required roles"""
    if not required_role_ids:
        return True  # No role requirements
    
    user_role_ids = [role.id for role in user.roles]
    return any(role_id in user_role_ids for role_id in required_role_ids)


def has_admin_permission(user: discord.Member, guild: discord.Guild) -> bool:
    """Check if user has admin permissions"""
    # Server owner always has permission
    if guild and user.id == guild.owner_id:
        return True
    
    # Check for administrator permission
    if user.guild_permissions.administrator:
        return True
    
    # Check for manage_guild permission
    if user.guild_permissions.manage_guild:
        return True
    
    return False


def format_permissions_error(missing_permissions: List[str]) -> str:
    """Format a permissions error message"""
    if len(missing_permissions) == 1:
        return f"You need the **{missing_permissions[0]}** permission to use this command."
    else:
        permissions = ", ".join(missing_permissions[:-1]) + f" or **{missing_permissions[-1]}**"
        return f"You need one of the following permissions: **{permissions}**."