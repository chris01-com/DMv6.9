import discord
import logging
from datetime import datetime
import math
import random

logger = logging.getLogger(__name__)


# Enhanced color palette for professional appearance
class Colors:
    PRIMARY = 0x2C3E50  # Dark blue-gray
    SECONDARY = 0x3498DB  # Blue
    SUCCESS = 0x27AE60  # Green
    WARNING = 0xF39C12  # Orange
    ERROR = 0xE74C3C  # Red
    INFO = 0x9B59B6  # Purple
    GOLD = 0xF1C40F  # Gold for top ranks
    SILVER = 0xBDC3C7  # Silver for second place
    BRONZE = 0xD35400  # Bronze for third place
    GRADIENT_START = 0x667eea  # Gradient colors
    GRADIENT_END = 0x764ba2
    RANK_COLORS = {
        "Demon God": 0x36393F,  # Gray (from screenshot)
        "Heavenly Demon": 0x4B0082,  # Purple/Indigo (from screenshot)
        "Demon Sovereign": 0x6A0D83,  # Dark purple (between Heavenly Demon and Supreme Demon)
        "Supreme Demon": 0xE74C3C,  # Red (from screenshot)
        "Guardian": 0x3498DB,  # Blue (from screenshot)
        "Demon King": 0x8B0000,  # Dark red (fitting for King rank)
        "Demon Council": 0x9B59B6,  # Purple (from screenshot)
        "Demonic Commander": 0x8E44AD,  # Deep purple (between council and young master)
        "Young Master": 0x3498DB,  # Blue (from screenshot)
        "Core Disciple": 0xF1C40F,  # Yellow (from screenshot - Hermes role)
        "Inner Disciple": 0x3498DB,  # Blue (similar to other roles)
        "Outer Disciple": 0x95A5A6,  # Light gray
        "Servant": 0x7F8C8D  # Dark gray
    }


def format_large_number(number):
    """Format large numbers with appropriate suffixes"""
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    elif number >= 1_000:
        return f"{number / 1_000:.1f}K"
    else:
        return str(number)


# Role configuration constants
SPECIAL_ROLES = {
    1266143259801948261: "Demon God",
    1281115906717650985: "Heavenly Demon",
    1415022514534486136: "Demon Sovereign",
    1304283446016868424: "Supreme Demon",
    1276607675735736452: "Guardian",
    1415242286929022986: "Demon King",
    1266242655642456074: "Demon Council",
    1400055033592287263: "Demonic Commander",
    1390279781827874937: "Young Master"
}

# Disciple role hierarchy with actual Discord role names (from getrank dropdown)
DISCIPLE_ROLES = {
    1382602945752727613: {
        "name": "Primordial Demon",
        "points": 2000
    },
    1391059979167072286: {
        "name": "Divine Demon",
        "points": 1500
    },
    1391060071189971075: {
        "name": "Ancient Demon",
        "points": 1250
    },
    1268528848740290580: {
        "name": "Arch Demon",
        "points": 750
    },
    1308823860740624384: {
        "name": "True Demon",
        "points": 500
    },
    1391059841505689680: {
        "name": "Great Demon",
        "points": 350
    },
    1308823565881184348: {
        "name": "Upper Demon",
        "points": 200
    },
    1266826177163694181: {
        "name": "Lower Demon",
        "points": 100
    },
    1389474689818296370: {
        "name": "Demon Apprentice",
        "points": 0
    },
    1266826663203700767: {
        "name": "Demon Servant",
        "points": 0
    }
}

# Enhanced rank requirements with quest and progression requirements
ENHANCED_RANK_REQUIREMENTS = {
    1382602945752727613: {  # Primordial Demon (HIGHEST RANK)
        "name": "Primordial Demon",
        "points": 2000,
        "previous_rank": 1391059979167072286,  # Divine Demon
        "quest_requirements": {
            "Impossible": 6
        },
        "additional_requirements": []
    },
    1391059979167072286: {  # Divine Demon
        "name": "Divine Demon",
        "points": 1500,
        "previous_rank": 1391060071189971075,  # Ancient Demon
        "quest_requirements": {
            "Hard": 5,
            "Impossible": 1
        },
        "additional_requirements": []
    },
    1391060071189971075: {  # Ancient Demon
        "name": "Ancient Demon",
        "points": 1250,
        "previous_rank": 1268528848740290580,  # Arch Demon
        "quest_requirements": {
            "Hard": 4
        },
        "additional_requirements": []
    },
    1268528848740290580: {  # Arch Demon
        "name": "Arch Demon",
        "points": 750,
        "previous_rank": 1308823860740624384,  # True Demon
        "quest_requirements": {},
        "additional_requirements": []
    },
    1308823860740624384: {  # True Demon
        "name": "True Demon",
        "points": 500,
        "previous_rank": 1391059841505689680,  # Great Demon
        "quest_requirements": {},
        "additional_requirements": []
    },
    1391059841505689680: {  # Great Demon
        "name": "Great Demon",
        "points": 350,
        "previous_rank": 1308823565881184348,  # Upper Demon
        "quest_requirements": {},
        "additional_requirements": []
    },
    1308823565881184348: {  # Upper Demon
        "name": "Upper Demon",
        "points": 200,
        "previous_rank": 1266826177163694181,  # Lower Demon
        "quest_requirements": {},
        "additional_requirements": []
    },
    1266826177163694181: {  # Lower Demon
        "name": "Lower Demon",
        "points": 100,
        "previous_rank": 1389474689818296370,  # Demon Apprentice
        "quest_requirements": {},
        "additional_requirements": []
    },
    1389474689818296370: {  # Demon Apprentice
        "name": "Demon Apprentice",
        "points": 0,
        "previous_rank": None,
        "quest_requirements": {},
        "additional_requirements": []
    }
}

# Backwards compatibility - creates the point requirements lookup used by promotion system
ROLE_REQUIREMENTS = {
    role_id: data["points"]
    for role_id, data in DISCIPLE_ROLES.items()
}


def _get_point_based_fallback(points):
    """Get fallback rank based on points when no member object available"""
    return "Member"


def _get_qualified_roles(member, points):
    """Get list of roles the member qualifies for based on points"""
    if not member:
        return []

    user_roles = [role.id for role in member.roles]
    qualified_roles = []

    for role_id in user_roles:
        if role_id in ROLE_REQUIREMENTS:
            required_points = ROLE_REQUIREMENTS[role_id]
            if points >= required_points:
                qualified_roles.append((role_id, required_points))

    return qualified_roles


def get_rank_title_by_points(points, member=None):
    """Get rank title based on contribution points and member roles"""
    if not member:
        return _get_point_based_fallback(points)

    # Check for special roles that override contribution requirements
    # Find ALL special roles the user has and return the HIGHEST one
    user_special_roles = []
    for role in member.roles:
        if role.id in SPECIAL_ROLES:
            # Use role position to determine hierarchy (higher position = higher role)
            user_special_roles.append((role.id, role.position, SPECIAL_ROLES[role.id]))
    
    if user_special_roles:
        # Sort by Discord role position (highest first) and return the highest special role
        user_special_roles.sort(key=lambda x: x[1], reverse=True)
        return user_special_roles[0][2]  # Return the highest special role name

    # Get qualified roles
    qualified_roles = _get_qualified_roles(member, points)

    if qualified_roles:
        # Sort by required points (highest first) and return that role's name
        qualified_roles.sort(key=lambda x: x[1], reverse=True)
        highest_role_id = qualified_roles[0][0]
        # Find the role object and return its name
        for role in member.roles:
            if role.id == highest_role_id:
                return role.name

    # If no qualifying roles found, return fallback
    return "No Qualifying Role"


def get_qualifying_role_name(points, member):
    """Get the user's highest qualifying disciple role based on points and role possession"""
    if not member:
        return "Demon Servant"

    # Check for special roles first (highest priority) - these don't require points
    # Find ALL special roles the user has and return the HIGHEST one
    user_special_roles = []
    for role in member.roles:
        if role.id in SPECIAL_ROLES:
            # Use role position to determine hierarchy (higher position = higher role)
            user_special_roles.append((role.id, role.position, SPECIAL_ROLES[role.id]))
    
    if user_special_roles:
        # Sort by Discord role position (highest first) and return the highest special role
        user_special_roles.sort(key=lambda x: x[1], reverse=True)
        return user_special_roles[0][2]  # Return the highest special role name

    # Only show disciple roles if user has BOTH the Discord role AND enough points
    user_qualified_roles = []
    for role in member.roles:
        if role.id in DISCIPLE_ROLES:
            role_data = DISCIPLE_ROLES[role.id]
            required_points = role_data["points"]
            # User must have enough points to actually qualify
            if points >= required_points:
                user_qualified_roles.append(
                    (role.id, required_points, role_data["name"]))

    if user_qualified_roles:
        # Sort by required points (highest first) and return the highest qualified role
        user_qualified_roles.sort(key=lambda x: x[1], reverse=True)
        return user_qualified_roles[0][
            2]  # Return the role name they've actually earned

    # If user doesn't qualify for any disciple roles, return demon servant
    return "Demon Servant"


def get_user_role_display(member):
    """Get the user's highest Discord role name for display (legacy function)"""
    if not member:
        return "No Role"

    # Skip @everyone role and get highest role
    roles = [role for role in member.roles if role.name != "@everyone"]
    if not roles:
        return "No Role"

    # Return the highest role (Discord roles are ordered by hierarchy)
    highest_role = roles[-1]
    return highest_role.name


def get_rank_color(rank_title):
    """Get color for specific rank"""
    return Colors.RANK_COLORS.get(rank_title, Colors.PRIMARY)


def get_next_rank_info(points, member=None):
    """Get information about the next rank advancement"""
    current_rank = get_rank_title_by_points(points, member)

    # Define progression thresholds for new rank system
    thresholds = [100, 200, 350, 500, 750, 1000]
    threshold_names = [
        "Lower Warrior", "Middle Warrior", "High Warrior", "Sentry", "Warden", "Elder"
    ]

    for i, threshold in enumerate(thresholds):
        if points < threshold:
            points_needed = threshold - points
            progress_percentage = (points / threshold) * 100 if threshold > 0 else 0
            return {
                "next_rank": threshold_names[i],
                "points_needed": points_needed,
                "current_points": points,
                "threshold": threshold,
                "progress_percentage": progress_percentage
            }

    # User has reached Elder rank (max rank)
    return {
        "next_rank": "Elder",
        "points_needed": 0,
        "current_points": points,
        "threshold": 1000,
        "progress_percentage": 100.0,
        "max_rank_message": "🎉 You have reached your maximum rank in points! Now you may apply for the Elder rank if you wish to rank up. Congratulations on achieving the highest cultivation level!"
    }


async def get_total_guild_points(leaderboard_manager, guild_id):
    """Get total points for all members in a guild"""
    try:
        if hasattr(leaderboard_manager, 'pool') and leaderboard_manager.pool:
            async with leaderboard_manager.pool.acquire() as conn:
                result = await conn.fetchval(
                    '''
                    SELECT COALESCE(SUM(points), 0) FROM leaderboard WHERE guild_id = $1
                ''', guild_id)
                return result or 0
        return 0
    except Exception as e:
        logger.error(f"Error getting total guild points: {e}")
        return 0


def create_success_embed(title: str, description: str, additional_info: str = None) -> discord.Embed:
    """Create a success embed with green color"""
    embed = discord.Embed(
        title=f"✅ {title}",
        description=description,
        color=0x00FF00
    )
    if additional_info:
        embed.add_field(name="Details", value=additional_info, inline=False)
    return embed

def create_standard_embed(title: str, description: str = None) -> discord.Embed:
    """Create a standard embed with consistent styling"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=0x4B0082
    )
    return embed

def create_error_embed(title, description, additional_info=None, fields=None):
    """Create a beautiful error embed with proper Discord formatting"""
    # Dynamic red color palette
    base_colors = [0xE74C3C, 0xC0392B, 0xF39C12, 0xFF6B6B]
    current_color = base_colors[datetime.now().second % len(base_colors)]

    embed = discord.Embed(title=f"⚠ {title}",
                          description=description,
                          color=current_color,
                          timestamp=discord.utils.utcnow())

    if additional_info:
        embed.add_field(name="━━━━━━━━━ Error Details ━━━━━━━━━",
                        value=additional_info,
                        inline=False)

    if fields:
        for field in fields:
            name = field.get('name', 'Information')
            value = field.get('value', 'No data')
            inline = field.get('inline', False)
            embed.add_field(name=f"▸ {name}", value=value, inline=inline)

    embed.set_footer(text="Heavenly Demon Sect • Action Required")
    return embed


def create_info_embed(title, description, additional_info=None, fields=None):
    """Create a beautiful info embed with proper Discord formatting"""
    # Dynamic blue color palette
    base_colors = [0x3498DB, 0x5DADE2, 0x85C1E9, 0x1ABC9C]
    current_color = base_colors[datetime.now().second % len(base_colors)]

    embed = discord.Embed(title=f"ℹ {title}",
                          description=description,
                          color=current_color,
                          timestamp=discord.utils.utcnow())

    if additional_info:
        embed.add_field(name="━━━━━━━━━ Additional Information ━━━━━━━━━",
                        value=additional_info,
                        inline=False)

    if fields:
        for field in fields:
            name = field.get('name', 'Information')
            value = field.get('value', 'No data')
            inline = field.get('inline', False)
            embed.add_field(name=f"▸ {name}", value=value, inline=inline)

    embed.set_footer(text="Heavenly Demon Sect • Information System")
    return embed


def get_sect_authority_by_rank(member, points=0):
    """Determine sect authority level based on user's rank"""
    if not member:
        return "Sect Command"

    # Check for special high-authority roles first
    for role in member.roles:
        if role.id in SPECIAL_ROLES:
            rank_name = SPECIAL_ROLES[role.id]

            # Map ranks to authority levels
            if rank_name in ["Demon God"]:
                return "Divine Sovereignty"
            elif rank_name in ["Heavenly Demon"]:
                return "Heavenly Council"
            elif rank_name in ["Supreme Demon", "Guardian"]:
                return "Supreme Command"
            elif rank_name in ["Demon Council"]:
                return "Elder Council"
            elif rank_name in ["Demonic Commander", "Young Master"]:
                return "High Command"

    # Check disciple ranks based on points
    if points >= 1250:  # Divine/Ancient Demon level
        return "Inner Sanctum"
    elif points >= 750:  # Primordial/Arch Demon level
        return "Core Authority"
    elif points >= 350:  # True/Great Demon level
        return "Senior Command"
    elif points >= 100:  # Upper/Lower Demon level
        return "Demon Authority"
    else:  # Demon Apprentice level
        return "Apprentice Council"


def create_announcement_embed(title, description, author_name=None, author_member=None, author_points=0, announcement_type="general"):
    """Create a beautiful announcement embed with Heavenly Demon theming"""

    # Define different styles based on announcement type
    announcement_styles = {
        "general": {
            "colors": [0x9B59B6, 0x8E44AD, 0x4B0082, 0xE74C3C, 0xF39C12],
            "title": "SECT PROCLAMATION",
            "header": "OFFICIAL DECREE",
            "icon": ""
        },
        "decree": {
            "colors": [0xFFD700, 0xDAA520, 0xB8860B, 0xFF8C00],
            "title": "IMPERIAL DECREE",
            "header": "SUPREME COMMAND",
            "icon": ""
        },
        "event": {
            "colors": [0x00CED1, 0x1E90FF, 0x4169E1, 0x6A5ACD],
            "title": "SECT GATHERING",
            "header": "EVENT ANNOUNCEMENT",
            "icon": ""
        },
        "mission": {
            "colors": [0xDC143C, 0xB22222, 0x8B0000, 0xFF4500],
            "title": "MISSION BRIEFING",
            "header": "TACTICAL DIRECTIVE",
            "icon": ""
        },
        "celebration": {
            "colors": [0xFF69B4, 0xFF1493, 0xFFB6C1, 0xFFC0CB],
            "title": "SECT CELEBRATION",
            "header": "JOYOUS OCCASION",
            "icon": ""
        },
        "warning": {
            "colors": [0xFF0000, 0xDC143C, 0xB22222, 0x8B0000],
            "title": "DISCIPLINARY NOTICE",
            "header": "SECT DISCIPLINE",
            "icon": ""
        }
    }

    style = announcement_styles.get(announcement_type, announcement_styles["general"])
    current_color = style["colors"][datetime.now().second % len(style["colors"])]

    embed = discord.Embed(
        description=f"**HEAVENLY DEMON SECT**\n{style['header']}",
        color=current_color,
        timestamp=discord.utils.utcnow()
    )

    # Main announcement content
    style = announcement_styles.get(announcement_type, announcement_styles["general"])
    embed.add_field(
        name=f"━━━━━━━━━ {title.upper()} ━━━━━━━━━",
        value=description,
        inline=False
    )


    # Authority section with dynamic authority level
    sect_authority = get_sect_authority_by_rank(author_member, author_points)
    authority_text = f"**Sect Authority:** {sect_authority}"
    if author_name:
        authority_text += f"\n**Proclaimed By:** {author_name}"
    authority_text += "\n**Status:** Official Decree"

    embed.add_field(
        name="━━━━━━━━━ Sect Authority ━━━━━━━━━",
        value=authority_text,
        inline=False
    )

    embed.set_footer(text="Heavenly Demon Sect • Official Communications")
    return embed


def create_leaderboard_embed(leaderboard_data,
                             current_page,
                             total_pages,
                             guild_name,
                             guild=None,
                             total_guild_points=0):
    """Create a spectacular advanced leaderboard embed with enhanced visual design"""

    # Dynamic color based on time for animated effect
    base_colors = [0x667eea, 0x764ba2, 0x4568dc, 0xb06ab3]
    current_color = base_colors[datetime.now().second % len(base_colors)]

    embed = discord.Embed(color=current_color,
                          timestamp=discord.utils.utcnow())

    if not leaderboard_data:
        embed.title = "⚔️ EMPTY REALM ⚔️"
        embed.description = "```css\n[ The Heavenly Demon Sect Awaits Worthy Disciples ]\n```"
        embed.add_field(
            name="═══════════════════════════════════════",
            value=
            "```yaml\nNo cultivators have begun their journey yet.\nComplete quests to etch your name in legend.\n\n❯ Use /list_quests to see available missions\n❯ Rise through the ranks of power\n❯ Claim your destiny among the demons```",
            inline=False)
        embed.set_footer(text="Heavenly Demon Sect • Recruitment Hall")
        return embed

    # Spectacular header with ASCII art borders
    embed.title = f"═══ ⚔️ HEAVENLY DEMON SECT POWER RANKINGS ⚔️ ═══"

    # Enhanced header with guild stats
    header_sections = []
    header_sections.append(
        f"```css\n[ {guild_name.upper()} CULTIVATION LEADERBOARD ]```")

    if total_guild_points:
        header_sections.append(
            f"```yaml\nTotal Sect Power: {format_large_number(total_guild_points)} Cultivation Points```"
        )

    header_sections.append(
        f"```diff\n+ Page {current_page} of {total_pages} • {len(leaderboard_data)} Disciples Shown +```"
    )

    embed.description = "\n".join(header_sections)

    # Categorize members by rank
    top_three = []  # Top 3
    elite_members = []  # 4-7
    regular_members = []  # 8+

    for i, member in enumerate(leaderboard_data):
        rank = member.get('rank', (current_page - 1) * 50 + i + 1)
        username = member.get('username', 'Unknown Cultivator')
        points = member.get('points', 0)
        user_id = member.get('user_id')

        # Get Discord member for role information
        discord_member = None
        if guild and user_id:
            try:
                user_id_int = int(user_id) if isinstance(user_id,
                                                         str) else user_id
                discord_member = guild.get_member(user_id_int)
            except Exception:
                pass

        # Get cultivation realm (role display) - with debug logging
        cultivation_realm = get_qualifying_role_name(points, discord_member)
        
        # Debug logging for rank selection
        if discord_member:
            user_role_names = [f"{role.name}(ID:{role.id},pos:{role.position})" for role in discord_member.roles if role.name != "@everyone"]
            logger.info(f"🔍 Leaderboard rank debug for {username}: roles={user_role_names}, points={points}, selected_realm={cultivation_realm}")
        username_display = username[:18] + "…" if len(
            username) > 18 else username

        member_data = {
            'rank': rank,
            'username': username_display,
            'points': points,
            'realm': cultivation_realm
        }

        # Categorize by rank
        if rank <= 3:
            top_three.append(member_data)
        elif rank <= 7:
            elite_members.append(member_data)
        else:
            regular_members.append(member_data)

    # ═══ TOP 3 ═══
    if top_three:
        top_text = "```css\n"
        for member in top_three:
            top_text += f"{member['rank']}. {member['username']}\n"
            top_text += f"   ├─ Points: {format_large_number(member['points'])}\n"
            top_text += f"   └─ Rank: {member['realm']}\n\n"

        top_text += "```"

        embed.add_field(name="┏━━━━━━━━━ 🏆 TOP 3 🏆 ━━━━━━━━━┓",
                        value=top_text,
                        inline=False)

    # ═══ ELITE MEMBERS (4-7) ═══
    if elite_members:
        elite_text = "```yaml\n"
        for member in elite_members:
            elite_text += f"{member['rank']}. {member['username']}\n"
            elite_text += f"   └─ {format_large_number(member['points'])} pts • {member['realm']}\n"
        elite_text += "```"

        embed.add_field(name="┏━━━━━━━━━ ◆ ELITE MEMBERS ◆ ━━━━━━━━━┓",
                        value=elite_text,
                        inline=False)

    # ═══ OTHER MEMBERS (8+) ═══
    if regular_members:
        # Split regular members into multiple fields to avoid 1024 char limit
        regular_fields = []
        current_text = "```diff\n"

        for i, member in enumerate(
                regular_members[:43]
        ):  # Show up to 43 members (50 total with top 3 + elite 4)
            member_line = f"+ {member['rank']:2d}. {member['username']}\n"
            member_line += f"     {format_large_number(member['points'])} pts • {member['realm']}\n"

            # Check if adding this member would exceed field limit (950 chars to stay safe)
            if len(current_text + member_line + "```") > 950:
                # Close current field and start new one
                current_text += "```"
                regular_fields.append(current_text)
                current_text = "```diff\n" + member_line
            else:
                current_text += member_line

        # Add the last field
        if current_text != "```diff\n":
            current_text += "```"
            regular_fields.append(current_text)

        # Add all regular member fields
        for i, field_text in enumerate(regular_fields):
            field_name = "┏━━━━━━ ◇ OTHER MEMBERS ◇ ━━━━━━┓" if i == 0 else "\u200b"
            embed.add_field(name=field_name, value=field_text, inline=False)

        # Show count if more members exist
        if len(regular_members) > 43:
            overflow_count = len(regular_members) - 43
            embed.add_field(
                name="\u200b",
                value=f"```css\n... and {overflow_count} more members ...```",
                inline=False)

    # ═══ SECT POWER ANALYSIS ═══
    page_total = sum(member.get('points', 0) for member in leaderboard_data)
    avg_power = page_total // len(leaderboard_data) if leaderboard_data else 0

    analysis_text = f"```yaml\nPage Power: {format_large_number(page_total)}\n"
    analysis_text += f"Average Cultivation: {format_large_number(avg_power)}\n"
    analysis_text += f"Members Shown: {len(leaderboard_data)}\n```"

    embed.add_field(name="┏━━━━━━━ 📊 SECT POWER ANALYSIS 📊 ━━━━━━━┓",
                    value=analysis_text,
                    inline=False)

    # Enhanced footer with cultivation wisdom
    wisdom_quotes = [
        "The path of cultivation is endless • Strength through perseverance",
        "Power flows to those who seek it • Rankings shift with dedication",
        "In the Heavenly Demon Sect, only the strong survive",
        "Cultivation points forge destiny • Rise through the ranks",
        "The weak serve the strong • Ascend or be forgotten"
    ]

    current_wisdom = wisdom_quotes[datetime.now().minute % len(wisdom_quotes)]
    embed.set_footer(text=f"Heavenly Demon Sect • {current_wisdom}")

    return embed


def create_user_stats_embed(user, stats, guild_name, profile=None):
    """Create a beautiful user statistics embed with proper Discord formatting"""
    role_display = get_qualifying_role_name(stats['points'], user)

    # Dynamic color palette
    base_colors = [0x3498DB, 0x5DADE2, 0x85C1E9, 0xAED6F1]
    current_color = base_colors[datetime.now().second % len(base_colors)]

    # Override with custom color if set
    if profile and profile.get('preferred_color'):
        try:
            current_color = int(profile['preferred_color'].replace('#', ''),
                                16)
        except:
            pass

    embed = discord.Embed(
        title=f"👤 {user.display_name} Stats",
        description=
        f"**Disciple:** {user.display_name}\n**Rank:** {role_display}\n**Guild:** {guild_name}",
        color=current_color,
        timestamp=discord.utils.utcnow())

    # Avatar display
    if user.avatar:
        embed.set_thumbnail(url=user.avatar.url)

    # Format datetime elegantly
    last_updated_str = format_datetime(
        stats['last_updated']) if stats.get('last_updated') else "Unknown"
    if isinstance(stats.get('last_updated'), str):
        last_updated_str = stats['last_updated'][:10]

    # Power metrics section
    embed.add_field(
        name="━━━━━━━━━ Power Metrics ━━━━━━━━━",
        value=
        f"**Contribution Points:** {format_large_number(stats['points'])}\n**Current Rank:** {role_display}\n**Last Activity:** {last_updated_str[:10]}\n**Status:** Active",
        inline=False)

    # Advancement tracking
    next_rank_info = get_next_rank_info(stats['points'], user)
    if next_rank_info.get('max_rank_message'):
        embed.add_field(
            name="━━━━━━━━━ Maximum Achievement ━━━━━━━━━",
            value=next_rank_info['max_rank_message'],
            inline=False)
    else:
        embed.add_field(
            name="━━━━━━━━━ Advancement Path ━━━━━━━━━",
            value=
            f"**Target Rank:** {next_rank_info['next_rank']}\n**Points Required:** {next_rank_info['points_needed']}",
            inline=False)

    # Quest statistics if available
    if stats.get('quests_completed', 0) > 0:
        embed.add_field(
            name="━━━━━━━━━ Mission Record ━━━━━━━━━",
            value=
            f"**Completed:** {stats.get('quests_completed', 0)}\n**Accepted:** {stats.get('quests_accepted', 0)}\n**Success Rate:** {(stats.get('quests_completed', 0) / max(1, stats.get('quests_accepted', 1))) * 100:.1f}%",
            inline=False)

    # Personal message
    if profile and profile.get('status_message'):
        embed.add_field(name="━━━━━━━━━ Personal Message ━━━━━━━━━",
                        value=profile['status_message'],
                        inline=False)

    embed.set_footer(text="Heavenly Demon Sect • Disciple Archive")
    return embed


def create_promotion_embed(member,
                           previous_role,
                           new_role,
                           current_points,
                           rank_title=None,
                           is_special=False):
    """Create a beautiful promotion embed with proper Discord formatting"""
    # Color based on new rank (use rank title if provided, otherwise role name)
    rank_color = get_rank_color(rank_title if rank_title else (new_role.name if new_role else "Unknown"))

    embed = discord.Embed(
        title=f"Rank Promotion",
        description=
        f"**{member.display_name}** has been promoted to a higher rank!",
        color=rank_color,
        timestamp=discord.utils.utcnow())

    # Avatar display
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)

    # Rank progression - show actual Discord roles
    previous_role_display = previous_role.mention if previous_role else "None"
    new_role_display = new_role.mention if new_role else "Unknown"

    if is_special:
        embed.add_field(
            name="━━━━━━━━━ Special Appointment ━━━━━━━━━",
            value=
            f"**Previous Role:** {previous_role_display}\n**New Role:** {new_role_display}",
            inline=False)
    else:
        embed.add_field(
            name="━━━━━━━━━ Rank Change ━━━━━━━━━",
            value=
            f"**Previous Role:** {previous_role_display}\n**New Role:** {new_role_display}\n**Points:** {format_large_number(current_points)}",
            inline=False)

    # Clan status - different for special roles
    if is_special:
        sect_info = f"**Clan:** Heavenly Demon Sect\n**Status:** Leadership Appointment"
        if new_role:
            sect_info += f"\n**Title:** {new_role.name}"
    else:
        sect_info = f"**Clan:** Heavenly Demon Sect\n**Status:** Merit-Based Promotion"
        if new_role:
            sect_info += f"\n**Role:** {new_role.name}"

    embed.add_field(name="━━━━━━━━━ Clan Status ━━━━━━━━━",
                    value=sect_info,
                    inline=False)

    # Comprehensive lore-based achievement messages for all roles
    achievement_proclamations = {
        # Servant/Base Level
        "Servant":
        "From the blood-soaked training grounds, your dark journey begins. Each scar tells a story of relentless pursuit.",

        # Outer Disciple Tier (Entry Cultivation)
        "Outer Disciple":
        "You have shattered your mortal limitations through countless nights of agonizing training.",
        "Outer Disciple - Initiate":
        "The forbidden qi flows through your meridians for the first time. Pain is your teacher, power is your reward.",
        "Outer Disciple - Adept":
        "Your foundation grows stronger with each drop of blood spilled in pursuit of demonic mastery.",

        # Inner Disciple Tier (Intermediate Cultivation)
        "Inner Disciple":
        "The sect's secret techniques whisper their dark truths to your battle-hardened soul.",
        "Inner Disciple - Scholar":
        "Ancient demonic texts reveal their mysteries to one who has proven worthy through suffering.",
        "Inner Disciple - Warrior":
        "Your blade drinks deep of enemy blood while your spirit grows ever darker.",

        # Core Disciple Tier (Advanced Cultivation)
        "Core Disciple":
        "The elders acknowledge your rise through mountains of corpses and rivers of sweat.",
        "Core Disciple - Elite":
        "Your demonic aura terrifies even veteran cultivators. The weak flee at your approach.",
        "Core Disciple - Prodigy":
        "Genius illuminated by darkness - your potential knows no earthly bounds.",

        # Leadership & Special Positions
        "Young Master":
        "Born of shadow and flame, your very existence commands respect from lesser beings.",
        "Demonic Commander":
        "You command legions of darkness with absolute authority. Your tactical brilliance and demonic prowess have earned you a position of unquestioned leadership among the sect's elite forces.",
        "Demon Council":
        "You sit upon the Throne of Bones, where your word becomes the law of the underworld.",
        "Supreme Demon":
        "Even the ancient demons kneel before your overwhelming presence. Fear follows in your wake.",
        "Guardian":
        "You are the eternal sentinel of our forbidden knowledge, keeper of secrets that drive mortals mad.",
        "Heavenly Demon":
        "The heavens themselves crack under the weight of your demonic authority. Gods whisper your name in terror.",
        "Demon God":
        "You have transcended all mortal and divine limitations. Reality bends to your indomitable will.",

        # Role-specific achievements by actual Discord role ID
        1393834291921813598:
        "The ultimate pinnacle of demonic cultivation - even concepts of good and evil bow before your transcendent might.",
        1281115906717650985:
        "The nine heavens tremble as your demonic qi pierces through celestial barriers.",
        1276607675735736452:
        "Ancient oaths bind you to protect our darkest secrets from unworthy eyes.",
        1304283446016868424:
        "Your mere presence causes lesser demons to prostrate themselves in absolute submission.",
        1266242655642456074:
        "The Council of Shadows acknowledges your wisdom forged in the crucible of countless battles.",
        1390279781827874937:
        "Nobility flows through your dark bloodline - leadership is your birthright, power your inheritance.",
        1400055033592287263:
        "You command legions of darkness with absolute authority. Your tactical brilliance and demonic prowess have earned you a position of unquestioned leadership among the sect's elite forces.",

        # Core Disciple role IDs (1500, 1250, 1000 points)
        1391059979167072286:
        "The Inner Sanctum opens its doors to one who has bathed in the blood of a thousand enemies.",
        1391060071189971075:
        "Your cultivation has reached heights where mountains crumble at your casual gesture.",
        1382602945752727613:
        "The sect's most guarded techniques are yours to command, earned through relentless sacrifice.",

        # Inner Disciple role IDs (750, 500, 350 points)
        1268528848740290580:
        "The forbidden arts flow through your meridians like liquid darkness.",
        1308823860740624384:
        "Your spirit weapon thirsts for battle, hungry for the qi of fallen foes.",
        1391059841505689680:
        "The sect's secret archives unlock their mysteries to your battle-tested wisdom.",

        # Outer Disciple role IDs (200, 100, 0 points)
        1393834291888259118:
        "The first seal of demonic power breaks within your dantian.",
        1266826177163694181:
        "Your foundation stone is laid with the blood of your enemies and the sweat of endless training.",
        1308823565881184348:
        "You step onto the path of darkness, leaving your mortal weakness behind forever."
    }

    # Get achievement text - try role ID first, then role name, then fallback
    achievement_text = None

    # If we have the actual role object, try by ID first
    if new_role:
        achievement_text = achievement_proclamations.get(new_role.id)

    # If no ID match, try by role name
    if not achievement_text and rank_title:
        achievement_text = achievement_proclamations.get(rank_title)

    # Ultimate fallback with lore
    if not achievement_text:
        role_name = rank_title if rank_title else (new_role.name if new_role else "Unknown Rank")
        achievement_text = f"Through blood, sweat, and unwavering determination, you have claimed the rank of {role_name}. The Heavenly Demon Sect grows stronger with your ascension."

    proclamation = achievement_text

    embed.add_field(name="💭 Achievement Message",
                    value=proclamation,
                    inline=False)

    embed.set_footer(text="Heavenly Demon Sect • Promotion Ceremony")

    return embed


def create_progress_bar(current, total, length=20):
    """Create a professional text-based progress bar"""
    if total == 0:
        percentage = 100
    else:
        percentage = min((current / total) * 100, 100)

    filled_length = int(length * percentage // 100)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"▐{bar}▌ {percentage:.1f}%"


def truncate_text(text, max_length=1000):
    """Truncate text to fit Discord embed limits"""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."


def format_datetime(dt):
    """Format datetime for display"""
    if isinstance(dt, datetime):
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    return str(dt)


def get_emoji_for_rank(rank_title):
    """Get emoji for rank title - disabled for clean embeds"""
    return ""  # No emojis in clean design


def validate_points(points):
    """Validate point values"""
    try:
        points = int(points)
        return max(0, points)  # Ensure points are never negative
    except (ValueError, TypeError):
        return 0


def get_quest_rank_color(rank):
    """Get color for quest rank"""
    colors = {
        "easy": Colors.SUCCESS,
        "normal": Colors.INFO,
        "medium": Colors.WARNING,
        "hard": Colors.ERROR,
        "impossible": Colors.PRIMARY
    }
    return colors.get(rank.lower(), Colors.INFO)


def create_quest_embed(quest,
                       progress=None,
                       show_progress=False,
                       team_info=None):
    """Create a beautiful quest embed with proper Discord formatting"""
    from bot.models import QuestRank, QuestCategory

    # Color scheme based on quest difficulty
    rank_colors = {
        QuestRank.EASY: 0x2ECC71,
        QuestRank.NORMAL: 0x3498DB,
        QuestRank.MEDIUM: 0xF39C12,
        QuestRank.HARD: 0xE74C3C,
        QuestRank.IMPOSSIBLE: 0x9B59B6
    }

    color = rank_colors.get(quest.rank, rank_colors[QuestRank.NORMAL])

    # Difficulty symbols
    difficulty_symbols = {
        QuestRank.EASY: "◇",
        QuestRank.NORMAL: "◆",
        QuestRank.MEDIUM: "◈",
        QuestRank.HARD: "♦",
        QuestRank.IMPOSSIBLE: "♠"
    }

    symbol = difficulty_symbols.get(quest.rank, "◆")

    embed = discord.Embed(title=f"{symbol} {quest.title}",
                          description=quest.description
                          if quest.description else "No description provided",
                          color=color,
                          timestamp=quest.created_at)

    # Mission details section
    mission_details = f"**Quest ID:** {quest.quest_id}\n**Difficulty:** {quest.rank.title()}\n**Category:** {quest.category.title()}\n**Status:** {quest.status.title()}\n"

    # Add team quest information
    if team_info:
        mission_details += f"**Type:** Team Quest ({team_info.team_size_required} members)\n"
        mission_details += f"**Members:** {len(team_info.team_members)}\n"
    else:
        mission_details += "**Type:** Solo Quest\n"

    mission_details += f"**Issued:** {quest.created_at.strftime('%Y-%m-%d %H:%M')}"

    embed.add_field(name="━━━━━━━━━ Mission Parameters ━━━━━━━━━",
                    value=mission_details,
                    inline=False)

    # Requirements section
    if quest.requirements:
        embed.add_field(name="━━━━━━━━━ Requirements ━━━━━━━━━",
                        value=truncate_text(quest.requirements, 800),
                        inline=False)

    # Reward showcase
    if quest.reward:
        embed.add_field(name="━━━━━━━━━ Rewards ━━━━━━━━━",
                        value=truncate_text(quest.reward, 800),
                        inline=False)

    # Progress tracking
    if show_progress and progress:
        progress_status = progress.status.title()
        progress_info = f"**Status:** {progress_status}\n"
        if progress.accepted_at:
            progress_info += f"**Started:** {format_datetime(progress.accepted_at)}"

        embed.add_field(name="━━━━━━━━━ Your Progress ━━━━━━━━━",
                        value=progress_info,
                        inline=False)

    embed.set_footer(text=f"Heavenly Demon Sect • Quest {quest.quest_id}")
    return embed


def create_team_quest_embed(team_quest, team_members, show_members=True):
    """Create a beautiful team quest embed with proper Discord formatting"""
    from bot.models import QuestRank

    # Colors for team quests
    rank_colors = {
        QuestRank.EASY: Colors.SUCCESS,
        QuestRank.NORMAL: Colors.PRIMARY,
        QuestRank.MEDIUM: Colors.WARNING,
        QuestRank.HARD: Colors.ERROR,
        QuestRank.IMPOSSIBLE: Colors.GOLD
    }

    color = rank_colors.get(team_quest.rank, Colors.GOLD)

    embed = discord.Embed(title=f"👥 Team Quest - {team_quest.title}",
                          color=color,
                          timestamp=team_quest.created_at)

    # Description
    if team_quest.description:
        embed.description = f"**{team_quest.description}**\n*Collaborative mission for team members*"

    # Quest specifications
    embed.add_field(
        name="━━━━━━━━━ Mission Details ━━━━━━━━━",
        value=
        f"**ID:** {team_quest.quest_id}\n**Difficulty:** {team_quest.rank.title()}\n**Team Size:** {len(team_members)}\n**Status:** {team_quest.status.title()}",
        inline=True)

    # Team capacity and timeline
    embed.add_field(
        name="━━━━━━━━━ Team Info ━━━━━━━━━",
        value=
        f"**Capacity:** {len(team_members)}/10 Members\n**Created:** {team_quest.created_at.strftime('%Y-%m-%d')}\n**Time:** {team_quest.created_at.strftime('%H:%M')}",
        inline=True)

    # Team member showcase
    if show_members and team_members:
        member_list = []
        for member in team_members[:8]:  # Show max 8 members
            member_list.append(f"▸ {member.get('username', 'Unknown')}")

        if len(team_members) > 8:
            member_list.append(f"▸ +{len(team_members) - 8} more members")

        embed.add_field(name="━━━━━━━━━ Team Members ━━━━━━━━━",
                        value="\n".join(member_list),
                        inline=False)

    # Requirements section
    if team_quest.requirements:
        embed.add_field(name="━━━━━━━━━ Requirements ━━━━━━━━━",
                        value=team_quest.requirements,
                        inline=False)

    # Reward display
    if team_quest.reward:
        embed.add_field(
            name="━━━━━━━━━ Team Rewards ━━━━━━━━━",
            value=f"{team_quest.reward}\n*(Awarded to ALL team members)*",
            inline=False)

    embed.set_footer(
        text=f"Heavenly Demon Sect • Team Quest {team_quest.quest_id}")

    return embed


def create_quest_list_embed(quests,
                            guild_name,
                            current_filter=None,
                            page=1,
                            total_pages=1):
    """Create a magnificent quest listing embed with stunning visual hierarchy"""
    embed = discord.Embed(title=f"◆ SECT MISSION BOARD ◆ {guild_name.upper()}",
                          color=Colors.GOLD,
                          timestamp=discord.utils.utcnow())

    if not quests:
        embed.description = """```yaml
╭─────────────────────────────────╮
│       NO ACTIVE MISSIONS        │
╰─────────────────────────────────╯
```"""
        embed.add_field(
            name="┏━━━ ◆ MISSION STATUS ◆ ━━━┓",
            value=
            "```diff\n- No quests match your current filters\n+ Try adjusting difficulty or category\n+ New missions are posted regularly\n```",
            inline=False)
        return embed

    # Spectacular header with filtering information
    filter_text = "All Available Missions"
    if current_filter:
        filter_text = f"Filtered: {current_filter}"

    embed.description = f"""```yaml
╔═══════════════════════════════════════╗
║          HEAVENLY DEMON SECT          ║
║            MISSION BOARD              ║
╠═══════════════════════════════════════╣
║  Filter: {filter_text:<20}     ║
║  Page: {page:>2} of {total_pages:<2}               ║
╚═══════════════════════════════════════╝
```"""

    # Organize quests by difficulty for beautiful display
    difficulty_groups = {}
    for quest in quests:
        difficulty = quest.rank.value if hasattr(quest.rank, 'value') else str(
            quest.rank)
        if difficulty not in difficulty_groups:
            difficulty_groups[difficulty] = []
        difficulty_groups[difficulty].append(quest)

    # Display each difficulty tier with stunning formatting
    difficulty_order = ['easy', 'normal', 'medium', 'hard', 'impossible']
    difficulty_symbols = {
        'easy': '◇',
        'normal': '◆',
        'medium': '◈',
        'hard': '♦',
        'impossible': '◆◇◆'
    }

    for difficulty in difficulty_order:
        if difficulty in difficulty_groups:
            quest_list = []
            for quest in difficulty_groups[
                    difficulty][:5]:  # Limit per section
                status_symbol = "●" if quest.status == "active" else "○"
                quest_list.append(
                    f"{status_symbol} `{quest.quest_id}` **{quest.title[:25]}{'...' if len(quest.title) > 25 else ''}**"
                )

            symbol = difficulty_symbols.get(difficulty, '◆')
            embed.add_field(
                name=f"┏━━━ {symbol} {difficulty.upper()} TIER {symbol} ━━━┓",
                value="```md\n" + "\n".join(quest_list) + "\n```",
                inline=False)

    # Navigation and usage information
    embed.add_field(
        name="┏━━━ ◆ MISSION PROTOCOLS ◆ ━━━┓",
        value=
        "```ini\n[View Details]: /quest_info <quest_id>\n[Accept Mission]: /accept_quest <quest_id>\n[Filter Options]: /list_quests with filters\n```",
        inline=True)

    embed.set_footer(
        text=f"◆ HEAVENLY DEMON SECT ◆ MISSION DIRECTORY ◆ {page}/{total_pages}"
    )

    return embed


def get_ordinal(number):
    """Convert number to ordinal (1st, 2nd, 3rd, etc.)"""
    if 10 <= number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f"{number}{suffix}"

def generate_funeral_message(display_name, highest_role, total_points, times_left):
    """Generate a demonic cultivation-themed funeral message"""
    import random

    messages = [
        f"{display_name}'s demonic qi has dispersed into the void, their path through our sect complete.",
        f"The Heavenly Demon acknowledges {display_name}'s sacrifice. Their soul joins the eternal darkness.",
        f"Blood and shadows remember {display_name}'s cultivation journey within our demonic realm.",
        f"{display_name} has shattered their mortal shell to pursue the forbidden arts elsewhere.",
        f"The crimson moon bears witness to {display_name}'s departure from our unholy order.",
        f"{display_name}'s demonic essence transcends this plane, seeking greater power beyond.",
        f"In the abyss of cultivation, {display_name} walks the path of eternal solitude.",
        f"The dark heavens call {display_name} to ascend beyond mortal comprehension.",
        f"{display_name}'s inner demon has guided them to realms unknown to our sect.",
        f"May {display_name}'s malevolent spirit find dominion in the netherworld.",
        f"The sect's shadow grows darker in {display_name}'s absence. Their legacy endures.",
        f"{display_name} has broken through mortality's chains to embrace the void.",
        f"Thunder echoes through the demonic realm as {display_name} departs our brotherhood.",
        f"The ancient spirits whisper {display_name}'s name in the winds of destruction.",
        f"{display_name}'s cultivation of darkness leads them beyond our earthly sect."
    ]

    return random.choice(messages)