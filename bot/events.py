import discord
from discord.ext import commands
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from bot.utils import create_error_embed, create_info_embed, create_success_embed, Colors, get_rank_title_by_points, create_promotion_embed

logger = logging.getLogger(__name__)

# Global dictionary to track pending retirement checks
pending_retirements = {}

def setup_events(bot, leaderboard_manager, welcome_manager=None):
    """Setup all bot events with enhanced error handling and logging"""

    @bot.event
    async def on_member_join(member):
        """Enhanced event for when a member joins the server - includes reincarnation tracking"""
        try:
            if not member.bot:  # Skip bots
                # Check for reincarnation (returning member) - with role-based logic
                await check_member_reincarnation_with_role_check(member, bot)

                await leaderboard_manager.add_member(
                    member.guild.id, member.id, member.display_name
                )
                logger.info(f"✓ Added new member {member.display_name} to leaderboard for guild {member.guild.name}")

                # Auto-update all active leaderboard views for this guild
                from bot.commands import update_active_leaderboards
                await update_active_leaderboards(member.guild.id)

        except Exception as e:
            # Check if it's a connection-related error
            if 'connection' in str(e).lower() or 'pool' in str(e).lower():
                logger.error(f"✗ Database connection error adding new member {member.display_name} to leaderboard: {e}")
            else:
                logger.error(f"✗ Error adding new member {member.display_name} to leaderboard: {e}")
            return False

    @bot.event
    async def on_member_remove(member):
        """Enhanced event for when a member leaves the server - includes funeral tracking"""
        try:
            if not member.bot:  # Skip bots
                # Check if member has or had the funeral role (ID: 1268889388033642517) 
                FUNERAL_ROLE_ID = 1268889388033642517
                has_funeral_role = any(role.id == FUNERAL_ROLE_ID for role in member.roles)

                # Always save departure record, but only process funeral if they have the role
                await save_member_departure(member, bot, has_funeral_role)

                # Only send funeral embed if member currently has the special role
                if has_funeral_role:
                    await process_member_funeral(member, bot, has_funeral_role)
                else:
                    logger.info(f"🚫 {member.display_name} left without funeral role - no funeral embed sent")

                await leaderboard_manager.remove_member(member.guild.id, member.id)
                logger.info(f"✓ Removed member {member.display_name} from leaderboard for guild {member.guild.name}")

                # Auto-update all active leaderboard views for this guild
                from bot.commands import update_active_leaderboards
                await update_active_leaderboards(member.guild.id)

        except Exception as e:
            logger.error(f"✗ Error removing member {member.display_name} from leaderboard: {e}")

    @bot.event
    async def on_member_update(before, after):
        """Enhanced event for when a member's roles change - handles rank promotions"""
        try:
            if before.bot:  # Skip bots
                return

            # Check if roles have changed
            before_roles = set(before.roles)
            after_roles = set(after.roles)

            # Get newly added roles
            added_roles = after_roles - before_roles
            removed_roles = before_roles - after_roles

            if not added_roles and not removed_roles:
                return  # No role changes

            # Get member's current contribution points
            user_stats = await leaderboard_manager.get_user_stats(after.guild.id, after.id)
            if not user_stats:
                logger.warning(f"No stats found for {after.display_name} in role update event")
                return

            # Get points with correct priority (use leaderboard points as primary source)
            current_points = user_stats.get('points', user_stats.get('total_points_earned', 0))

            # Debug logging for point retrieval issues
            logger.info(f"🔍 Points debug for {after.display_name}: total_points_earned={user_stats.get('total_points_earned')}, points={user_stats.get('points')}, final={current_points}")

            # Check for welcome automation trigger (specific role added)
            if added_roles and welcome_manager:
                WELCOME_TRIGGER_ROLE = 1268889388033642517
                logger.info(f"🔍 Checking {len(added_roles)} added roles for welcome trigger: {[r.id for r in added_roles]}")
                for role in added_roles:
                    if role.id == WELCOME_TRIGGER_ROLE:
                        logger.info(f"🎯 Welcome trigger role detected for {after.display_name}")
                        result = await welcome_manager.process_new_member(after, bot)
                        logger.info(f"🎯 Welcome processing result: {result}")

                        # Check for pending reincarnation
                        await check_pending_reincarnation(after, bot)
                        break
                else:
                    logger.info(f"🔍 No welcome trigger role found in added roles")

            # Check for rank promotions with newly added roles
            if added_roles:
                logger.info(f"🔍 Checking rank promotion for {after.display_name} with {len(added_roles)} new roles")
                await check_rank_promotion(after, added_roles, current_points, bot)

            # Check for retirement notifications with removed roles (with delay)
            if removed_roles:
                await schedule_retirement_check(after, removed_roles, bot)

            # Check if this role addition cancels a pending retirement
            if added_roles:
                await cancel_retirement_if_promoted(after, added_roles)

            # Update active leaderboards if roles changed
            from bot.commands import update_active_leaderboards
            await update_active_leaderboards(after.guild.id)

        except Exception as e:
            logger.error(f"✗ Error in member update event for {after.display_name}: {e}")

    async def check_rank_promotion(member, added_roles, current_points, bot):
        """Check if role addition qualifies for rank promotion congratulations"""
        try:
            # Import role requirements from utils.py to ensure consistency
            from bot.utils import DISCIPLE_ROLES, SPECIAL_ROLES

            # Check if member has any special roles (Young Master and above) - these are immune to points
            member_role_ids = [role.id for role in member.roles]
            has_special_role = any(role_id in SPECIAL_ROLES for role_id in member_role_ids)

            # Use the exact role definitions from utils.py for consistency
            rank_roles = {}
            for role_id, data in DISCIPLE_ROLES.items():
                rank_roles[role_id] = {
                    "rank": data["name"], 
                    "points_required": data["points"]
                }

            # Check if any added roles qualify for promotion congratulations
            for role in added_roles:
                logger.info(f"🔍 Checking role {role.name} (ID: {role.id}) for promotion notification")

                # Check if this is a special role (Young Master and above) - always congratulate these
                if role.id in SPECIAL_ROLES:
                    # Special roles are immune to point requirements
                    special_rank = SPECIAL_ROLES[role.id]
                    logger.info(f"✅ Triggering special role promotion for {member.display_name}: {special_rank}")
                    await send_promotion_congratulations(member, special_rank, current_points, role, bot, is_special=True)
                    logger.info(f"✅ Special role promotion sent: {member.display_name} promoted to {special_rank}")
                    break
                elif role.id in rank_roles:
                    # Check point requirements for disciple roles (remove restriction on special roles)
                    rank_info = rank_roles[role.id]
                    logger.info(f"🔍 Disciple role found: {rank_info['rank']}, points required: {rank_info['points_required']}, current: {current_points}")

                    # Check if member meets point requirements OR has special role (flexibility)
                    if current_points >= rank_info["points_required"] or has_special_role:
                        # Send promotion congratulations with actual role name
                        logger.info(f"✅ Triggering disciple role promotion for {member.display_name}: {rank_info['rank']}")
                        await send_promotion_congratulations(member, rank_info['rank'], current_points, role, bot)
                        logger.info(f"✅ Disciple role promotion sent: {member.display_name} promoted to {rank_info['rank']}")
                        break  # Only send one promotion message per update
                    else:
                        logger.warning(f"⚠️ Points requirement not met for {member.display_name}: needs {rank_info['points_required']}, has {current_points}")
                else:
                    logger.debug(f"🔍 Role {role.name} (ID: {role.id}) not in promotion roles")

        except Exception as e:
            logger.error(f"✗ Error checking rank promotion for {member.display_name}: {e}")

    async def schedule_retirement_check(member, removed_roles, bot):
        """Schedule a retirement check with 1-minute delay - only triggers if user loses ALL special roles"""
        try:
            # Import role requirements from utils.py to ensure consistency
            from bot.utils import SPECIAL_ROLES

            # Check if any removed roles are special roles
            removed_special_roles = [role for role in removed_roles if role.id in SPECIAL_ROLES]

            if not removed_special_roles:
                return  # No special roles were removed, no retirement needed

            # Check if user still has any remaining special roles
            remaining_special_roles = [role for role in member.roles if role.id in SPECIAL_ROLES]

            if remaining_special_roles:
                logger.info(f"🔍 {member.display_name} still has special roles: {[r.name for r in remaining_special_roles]} - no retirement")
                return  # User still has special roles, no retirement

            # User has lost ALL special roles - schedule retirement check
            user_key = f"{member.guild.id}_{member.id}"

            # Cancel any existing retirement check for this user
            if user_key in pending_retirements:
                pending_retirements[user_key].cancel()

            # Schedule new retirement check with delay
            last_removed_role = removed_special_roles[-1]  # Use the last removed special role
            task = asyncio.create_task(
                delayed_retirement_check(member, last_removed_role, SPECIAL_ROLES[last_removed_role.id], bot)
            )
            pending_retirements[user_key] = task

            logger.info(f"🕐 Scheduled retirement check for {member.display_name} - lost ALL special roles (last: {last_removed_role.name})")

        except Exception as e:
            logger.error(f"✗ Error scheduling retirement check for {member.display_name}: {e}")

    async def cancel_retirement_if_promoted(member, added_roles):
        """Cancel pending retirement if user gets a higher role"""
        try:
            user_key = f"{member.guild.id}_{member.id}"

            if user_key not in pending_retirements:
                return  # No pending retirement

            # Import role requirements from utils.py to ensure consistency  
            from bot.utils import DISCIPLE_ROLES, SPECIAL_ROLES

            # Use the exact role IDs from utils.py (both disciple and special roles)
            important_role_ids = set(DISCIPLE_ROLES.keys()) | set(SPECIAL_ROLES.keys())

            # Check if any added roles are important (indicating promotion, not retirement)
            for role in added_roles:
                if role.id in important_role_ids:
                    # Cancel retirement - this is a promotion
                    pending_retirements[user_key].cancel()
                    del pending_retirements[user_key]
                    logger.info(f"❌ Cancelled retirement check for {member.display_name} (promoted to: {role.name})")
                    break

        except Exception as e:
            logger.error(f"✗ Error cancelling retirement check for {member.display_name}: {e}")

    async def delayed_retirement_check(member, removed_role, role_rank, bot):
        """Wait 1 minute then send retirement notification if still valid"""
        try:
            await asyncio.sleep(60)  # Wait 1 minute

            # If we reach here, no promotion happened - send retirement notification
            await send_retirement_notification(member, removed_role, role_rank, bot)

            # Clean up
            user_key = f"{member.guild.id}_{member.id}"
            if user_key in pending_retirements:
                del pending_retirements[user_key]

        except asyncio.CancelledError:
            # Task was cancelled - retirement was prevented by promotion
            logger.info(f"🚫 Retirement check cancelled (promotion detected)")
        except Exception as e:
            logger.error(f"✗ Error in delayed retirement check: {e}")

    async def send_promotion_congratulations(member, new_rank, current_points, role_received=None, bot=None, is_special=False):
        """Send rank promotion congratulations message"""
        try:
            # Import role definitions to find previous role
            from bot.utils import DISCIPLE_ROLES, SPECIAL_ROLES

            # Get the previous role by checking what they had before (excluding the new role)
            temp_member_roles = [role for role in member.roles if role != role_received]
            previous_role = None

            # Find the highest ranking role from previous roles
            all_rank_roles = {**DISCIPLE_ROLES, **SPECIAL_ROLES}
            highest_priority = -1

            for role in temp_member_roles:
                if role.id in all_rank_roles:
                    # Use role position as priority for Discord roles
                    if role.position > highest_priority:
                        highest_priority = role.position
                        previous_role = role

            # Create beautiful promotion embed with actual Discord roles
            embed = create_promotion_embed(member, previous_role, role_received, current_points, new_rank, is_special)

            # Get configured notification channel using channel config
            if not bot:
                logger.error("❌ Bot instance not provided to promotion notification")
                return

            from bot.config import ChannelConfig
            channel_config = ChannelConfig(bot.database)
            notification_channel_id = await channel_config.get_notification_channel(member.guild.id)

            # Determine where to send the notification
            if notification_channel_id:
                # Use configured channel
                channel = member.guild.get_channel(notification_channel_id)
                if channel and channel.permissions_for(member.guild.me).send_messages:
                    await channel.send(content=f"{member.mention}", embed=embed)
                    logger.info(f"✅ Sent promotion notification to configured channel #{channel.name}")
                else:
                    # Fallback to first available channel
                    await send_to_fallback_channel(member.guild, embed, member)
            else:
                # No channel configured, use fallback
                await send_to_fallback_channel(member.guild, embed, member)

            # Send DM to the user
            await send_promotion_dm(member, embed)

        except Exception as e:
            logger.error(f"❌ Error sending rank promotion congratulations: {e}")

    async def send_retirement_notification(member, role_removed=None, role_rank=None, bot=None):
        """Send retirement notification message with standard embed format"""
        try:
            # Create retirement information text
            retirement_info = f"**{member.display_name}** has retired from the Heavenly Demon Sect."

            # Add previous rank information if available
            if role_removed and role_rank:
                retirement_info += f"\n\n**Previous Rank:** {role_rank}"
                retirement_info += f"\n**Role:** {role_removed.name}"
            elif role_removed:
                retirement_info += f"\n\n**Previous Role:** {role_removed.name}"

            # Additional retirement details
            additional_info = "• No longer active in sect activities\n• Contribution points preserved\n• Welcome to return anytime"

            # Create retirement embed with standard formatting like other bot embeds
            embed = create_info_embed(
                title="Retirement",
                description=retirement_info,
                additional_info=additional_info
            )

            # Add member mention field
            embed.add_field(
                name="Member",
                value=member.mention,
                inline=True
            )

            # Get configured retirement channel
            if not bot:
                logger.error("❌ Bot instance not provided to retirement notification")
                return

            from bot.config import ChannelConfig
            channel_config = ChannelConfig(bot.database)
            retirement_channel_id = await channel_config.get_retirement_channel(member.guild.id)

            # Send to retirement channel
            if retirement_channel_id:
                channel = member.guild.get_channel(retirement_channel_id)
                if channel and channel.permissions_for(member.guild.me).send_messages:
                    await channel.send(embed=embed)
                    logger.info(f"✅ Sent retirement notification to configured channel #{channel.name}")
                else:
                    # Fallback to first available channel
                    await send_to_fallback_channel(member.guild, embed)
            else:
                # No channel configured, use fallback
                await send_to_fallback_channel(member.guild, embed)

        except Exception as e:
            logger.error(f"❌ Error sending retirement notification: {e}")

    async def send_to_fallback_channel(guild, embed, member=None):
        """Send message to the first available channel as fallback"""
        try:
            logger.info(f"🔄 Attempting fallback notification for guild {guild.name}")

            # Try to find a general or announcements channel first
            preferred_names = ['general', 'announcements', 'leaderboard', 'bot-commands']

            for channel_name in preferred_names:
                channel = discord.utils.get(guild.text_channels, name=channel_name)
                if channel and channel.permissions_for(guild.me).send_messages:
                    if member:
                        await channel.send(content=f"{member.mention}", embed=embed)
                    else:
                        await channel.send(embed=embed)
                    logger.info(f"✅ Sent notification to fallback channel #{channel.name}")
                    return

            # If no preferred channels found, use the first available text channel
            logger.info(f"📍 Trying first available text channel from {len(guild.text_channels)} channels")
            for channel in guild.text_channels:
                logger.info(f"🔍 Testing channel #{channel.name} - can send: {channel.permissions_for(guild.me).send_messages}")
                if channel.permissions_for(guild.me).send_messages:
                    if member:
                        await channel.send(content=f"{member.mention}", embed=embed)
                    else:
                        await channel.send(embed=embed)
                    logger.info(f"✅ Successfully sent notification to available channel #{channel.name}")
                    return

            logger.warning(f"⚠️ No available channels found to send notification in {guild.name}")

        except Exception as e:
            logger.error(f"❌ Error sending to fallback channel: {e}")

    async def send_promotion_dm(member, embed):
        """Send promotion notification to user's DMs"""
        try:
            # Send DM to the user
            await member.send(embed=embed)
            logger.info(f"✅ Sent promotion DM to {member.display_name}")

        except discord.Forbidden:
            logger.warning(f"⚠️ Cannot send DM to {member.display_name} - DMs are disabled")
        except discord.HTTPException as e:
            logger.error(f"❌ Failed to send DM to {member.display_name}: {e}")

    @bot.event
    async def on_guild_join(guild):
        """Initialize leaderboard when bot joins a new guild"""
        try:
            logger.info(f"🆕 Bot joined new guild: {guild.name} (ID: {guild.id})")

            # Initialize leaderboard for all non-bot members
            member_count = 0
            for member in guild.members:
                if not member.bot:
                    await leaderboard_manager.add_member(guild.id, member.id, member.display_name)
                    member_count += 1

            logger.info(f"✅ Initialized leaderboard for {guild.name} with {member_count} members")

        except Exception as e:
            # Check if it's a connection-related error
            if 'connection' in str(e).lower() or 'pool' in str(e).lower():
                logger.error(f"❌ Database connection error initializing guild {guild.name}: {e}")
            else:
                logger.error(f"❌ Error initializing guild {guild.name}: {e}")
            return False

    @bot.event
    async def on_guild_remove(guild):
        """Cleanup when bot leaves a guild"""
        try:
            logger.info(f"👋 Bot left guild: {guild.name} (ID: {guild.id})")
            # Note: We don't automatically delete data in case bot is re-added

        except Exception as e:
            logger.error(f"❌ Error during guild leave cleanup: {e}")

    @bot.event
    async def on_ready():
        """Bot ready event"""
        logger.info(f"✅ {bot.user} is now online and ready!")
        logger.info(f"📊 Connected to {len(bot.guilds)} guilds")

        # Initialize leaderboards for all guilds if needed
        for guild in bot.guilds:
            try:
                # Add any missing members to leaderboard
                for member in guild.members:
                    if not member.bot:
                        await leaderboard_manager.add_member(guild.id, member.id, member.display_name)

            except Exception as e:
                # Check if it's a connection-related error
                if 'connection' in str(e).lower() or 'pool' in str(e).lower():
                    logger.error(f"❌ Database connection error initializing guild {guild.name} on ready: {e}")
                else:
                    logger.error(f"❌ Error initializing guild {guild.name} on ready: {e}")
                return False

    @bot.event
    async def on_command_error(ctx, error):
        """Global command error handler"""
        logger.error(f"❌ Command error in {ctx.command}: {error}")

        if isinstance(error, commands.MissingPermissions):
            embed = create_error_embed(
                "Permission Denied",
                "You don't have the required permissions to use this command."
            )
            await ctx.send(embed=embed, ephemeral=True)
        elif isinstance(error, commands.CommandNotFound):
            # Ignore command not found errors
            pass
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = create_error_embed(
                "Missing Argument",
                f"Missing required argument: {error.param}"
            )
            await ctx.send(embed=embed, ephemeral=True)
        else:
            embed = create_error_embed(
                "Command Error",
                "An unexpected error occurred while processing your command."
            )
            await ctx.send(embed=embed, ephemeral=True)

    @bot.event
    async def on_application_command_error(interaction, error):
        """Global application command error handler"""
        logger.error(f"❌ Application command error: {error}")

        embed = create_error_embed(
            "Command Error",
            "An error occurred while processing your command. Please try again later."
        )

        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except:
            logger.error("❌ Failed to send error response to user")

# Funeral and Reincarnation System Functions
async def save_member_departure(member, bot, has_funeral_role):
    """Save member departure record regardless of funeral role status"""
    try:
        # Get member's user stats for departure record
        user_stats = await bot.database.get_user_stats(member.guild.id, member.id)
        total_points = 0
        if user_stats:
            total_points = user_stats.get('total_points_earned', user_stats.get('points', 0))

        # Get member's highest role (excluding @everyone)
        highest_role = None
        member_roles = [r for r in member.roles if r != member.guild.default_role]
        if member_roles:
            highest_role = max(member_roles, key=lambda r: r.position).name

        # Check if member previously departed
        previous_departure = await bot.database.get_departed_member(member.id, member.guild.id)
        times_left = 1
        if previous_departure:
            times_left = previous_departure.times_left + 1

        # Create departed member record
        from bot.models import DepartedMember
        from bot.utils import generate_funeral_message

        # Handle timezone for join_date properly (ensure timezone-naive for database)
        join_date = None
        if member.joined_at:
            if member.joined_at.tzinfo is None:
                # Already timezone-naive, use as-is
                join_date = member.joined_at
            else:
                # Convert timezone-aware to timezone-naive UTC
                join_date = member.joined_at.astimezone(timezone.utc).replace(tzinfo=None)

        departed_member = DepartedMember(
            member_id=member.id,
            guild_id=member.guild.id,
            username=member.name,
            display_name=member.display_name,
            avatar_url=str(member.avatar.url) if member.avatar else None,
            highest_role=highest_role,
            total_points=total_points,
            join_date=join_date,
            leave_date=datetime.now(timezone.utc).replace(tzinfo=None),
            times_left=times_left,
            funeral_message=generate_funeral_message(member.display_name, highest_role, total_points, times_left),
            had_funeral_role=has_funeral_role
        )

        # Save to database
        await bot.database.save_departed_member(departed_member)
        logger.info(f"💾 Saved departure record for {member.display_name} (Had funeral role: {has_funeral_role})")

    except Exception as e:
        logger.error(f"❌ Error saving member departure for {member.display_name}: {e}")

async def process_member_funeral(member, bot, has_funeral_role):
    """Process funeral for a departing member with the special role"""
    try:
        # Get member's user stats for funeral record
        user_stats = await bot.database.get_user_stats(member.guild.id, member.id)
        total_points = 0
        if user_stats:
            total_points = user_stats.get('total_points_earned', user_stats.get('points', 0))

        # Get member's highest role (excluding @everyone)
        highest_role = None
        member_roles = [r for r in member.roles if r != member.guild.default_role]
        if member_roles:
            highest_role = max(member_roles, key=lambda r: r.position).name

        # Check if member previously departed
        previous_departure = await bot.database.get_departed_member(member.id, member.guild.id)
        times_left = 1
        if previous_departure:
            times_left = previous_departure.times_left + 1

        # Get the departed member record (already saved by save_member_departure)
        departed_member = await bot.database.get_departed_member(member.id, member.guild.id)

        if departed_member and has_funeral_role:
            # Send funeral notification only if they had the role
            await send_funeral_notification(member, departed_member, bot)
            logger.info(f"⚰️ Processed funeral for {member.display_name} (Had funeral role: {has_funeral_role})")
        else:
            logger.info(f"🚫 No funeral sent for {member.display_name} - role requirement not met")

    except Exception as e:
        logger.error(f"❌ Error processing funeral for {member.display_name}: {e}")

async def check_member_reincarnation_with_role_check(member, bot):
    """Check if joining member is a returning member - role-based reincarnation logic"""
    try:
        logger.info(f"🔄 Checking reincarnation for {member.display_name} (ID: {member.id})")

        # Check if this member has a previous departure record
        departed_member = await bot.database.get_departed_member(member.id, member.guild.id)

        if departed_member:
            logger.info(f"✅ Found departed member record for {member.display_name}")

            # Check if they had the funeral role when they left
            if departed_member.had_funeral_role:
                logger.info(f"🎭 Member previously had funeral role - checking current role status")

                # Check if they currently have the funeral role
                FUNERAL_ROLE_ID = 1268889388033642517
                has_current_role = any(role.id == FUNERAL_ROLE_ID for role in member.roles)

                if has_current_role:
                    # They have the role now - send reincarnation notification
                    await process_reincarnation_notification(member, departed_member, bot)
                else:
                    # They don't have the role yet - add to pending reincarnations
                    logger.info(f"⏳ Adding {member.display_name} to pending reincarnations - waiting for role")
                    await bot.database.add_pending_reincarnation(member.id, member.guild.id)
            else:
                # They never had the funeral role, so no reincarnation notification needed
                logger.info(f"🚫 {member.display_name} never had funeral role - no reincarnation notification")
        else:
            logger.info(f"ℹ️ No previous departure record found for {member.display_name} - new member")

    except Exception as e:
        logger.error(f"❌ Error checking reincarnation for {member.display_name}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

async def check_pending_reincarnation(member, bot):
    """Check if member has pending reincarnation and process it"""
    try:
        FUNERAL_ROLE_ID = 1268889388033642517
        has_funeral_role = any(role.id == FUNERAL_ROLE_ID for role in member.roles)

        if has_funeral_role:
            # Check if they have a pending reincarnation
            pending = await bot.database.get_pending_reincarnation(member.id, member.guild.id)

            if pending:
                logger.info(f"🎉 Processing pending reincarnation for {member.display_name}")

                # Get their departed member record
                departed_member = await bot.database.get_departed_member(member.id, member.guild.id)

                if departed_member:
                    # Send reincarnation notification
                    await process_reincarnation_notification(member, departed_member, bot)

                    # Mark as notified (removes from pending)
                    await bot.database.mark_reincarnation_notified(member.id, member.guild.id)

                    logger.info(f"✅ Completed pending reincarnation for {member.display_name}")
    except Exception as e:
        logger.error(f"❌ Error checking pending reincarnation for {member.display_name}: {e}")

async def process_reincarnation_notification(member, departed_member, bot):
    """Process and send reincarnation notification"""
    try:
        # Update the departed member record
        update_success = await bot.database.update_departed_member_return(member.id, member.guild.id)
        logger.info(f"📊 Database update result: {update_success}")

        # Send reincarnation notification
        await send_reincarnation_notification(member, departed_member, bot)

        logger.info(f"🔄 Successfully processed reincarnation for returning member {member.display_name}")
    except Exception as e:
        logger.error(f"❌ Error processing reincarnation notification for {member.display_name}: {e}")

async def check_member_reincarnation(member, bot):
    """Check if joining member is a returning member (reincarnation) - LEGACY FUNCTION"""
    try:
        logger.info(f"🔄 Checking reincarnation for {member.display_name} (ID: {member.id})")

        # Check if this member has a previous departure record
        departed_member = await bot.database.get_departed_member(member.id, member.guild.id)

        if departed_member:
            logger.info(f"✅ Found departed member record for {member.display_name} - processing reincarnation!")

            # Update the departed member record
            update_success = await bot.database.update_departed_member_return(member.id, member.guild.id)
            logger.info(f"📊 Database update result: {update_success}")

            # Send reincarnation notification
            await send_reincarnation_notification(member, departed_member, bot)

            logger.info(f"🔄 Successfully processed reincarnation for returning member {member.display_name}")
        else:
            logger.info(f"ℹ️ No previous departure record found for {member.display_name} - new member")

    except Exception as e:
        logger.error(f"❌ Error checking reincarnation for {member.display_name}: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")

async def send_funeral_notification(member, departed_member, bot):
    """Send funeral notification to the designated channel"""
    try:
        from bot.utils import create_info_embed
        from bot.config import ChannelConfig

        # Create funeral embed with murim/cultivation theme
        funeral_title = "⚰️ Funeral Rites"

        # Create demonic cultivation-themed funeral description
        funeral_departure_messages = [
            f"**{departed_member.display_name}** has severed their ties to our demonic brotherhood.",
            f"**{departed_member.display_name}** has vanished into the shadow realm beyond our reach.",
            f"**{departed_member.display_name}** has answered the call of darker powers elsewhere.",
            f"**{departed_member.display_name}** has dissolved into the void, leaving our sect behind.",
            f"**{departed_member.display_name}** has been consumed by the eternal darkness beyond.",
            f"**{departed_member.display_name}** has abandoned the mortal coil to seek forbidden arts."
        ]

        import random
        description = random.choice(funeral_departure_messages)

        departure_context = {
            1: [
                "*Their soul takes its first journey into the unknown depths of existence.*",
                "*The first step on the path of eternal wandering has been taken.*",
                "*They embrace the void for the first time, seeking power beyond our realm.*"
            ],
            2: [
                "*Once again, they choose the path of shadows over our brotherhood.*",
                "*Their second departure cuts deeper into the fabric of our sect.*",
                "*The cycle of abandonment continues as they seek greater darkness.*"
            ],
            3: [
                "*Thrice they have forsaken us - a master of departure and solitude.*",
                "*Their third exodus marks them as a wanderer of the eternal abyss.*",
                "*Three times they have chosen the unknown over our demonic fellowship.*"
            ]
        }

        if departed_member.times_left <= 3:
            context_desc = random.choice(departure_context[departed_member.times_left])
        else:
            context_desc = f"*Their {get_ordinal(departed_member.times_left)} departure speaks of a restless demon seeking ultimate transcendence.*"

        description += f"\n{context_desc}"

        # Add funeral details with demonic theme
        funeral_details = []
        if departed_member.highest_role:
            funeral_details.append(f"**Final Demonic Rank:** {departed_member.highest_role}")
        if departed_member.total_points > 0:
            funeral_details.append(f"**Blood Contribution:** {departed_member.total_points:,} points")
        if departed_member.join_date:
            # Ensure both datetimes are timezone-aware for calculation
            join_date = departed_member.join_date
            leave_date = departed_member.leave_date
            if join_date.tzinfo is None:
                join_date = join_date.replace(tzinfo=timezone.utc)
            if leave_date.tzinfo is None:
                leave_date = leave_date.replace(tzinfo=timezone.utc)
            days_in_sect = (leave_date - join_date).days
            funeral_details.append(f"**Time in Dark Brotherhood:** {days_in_sect} days")

        additional_info = "\n".join(funeral_details) if funeral_details else "A demon's soul wanders the forbidden realms beyond mortal comprehension."

        if departed_member.funeral_message:
            additional_info += f"\n\n*{departed_member.funeral_message}*"

        # Create embed
        embed = create_info_embed(
            title=funeral_title,
            description=description,
            additional_info=additional_info
        )

        # Add member avatar if available
        if departed_member.avatar_url:
            embed.set_thumbnail(url=departed_member.avatar_url)

        # Get funeral channel
        channel_config = ChannelConfig(bot.database)
        funeral_channel_id = await channel_config.get_funeral_channel(member.guild.id)

        if funeral_channel_id:
            channel = member.guild.get_channel(funeral_channel_id)
            if channel and channel.permissions_for(member.guild.me).send_messages:
                await channel.send(embed=embed)
                logger.info(f"⚰️ Sent funeral notification to #{channel.name}")
                return

        # Fallback to notification channel or general
        await send_to_fallback_channel(member.guild, embed)

    except Exception as e:
        logger.error(f"❌ Error sending funeral notification: {e}")

async def send_reincarnation_notification(member, departed_member, bot):
    """Send reincarnation notification to the designated channel"""
    try:
        logger.info(f"🔄 Preparing reincarnation notification for {member.display_name}")
        from bot.utils import create_success_embed
        from bot.config import ChannelConfig

        # Create reincarnation embed with murim/cultivation theme
        reincarnation_title = "🔄 Reincarnation"

        # Calculate time away - ensure both datetimes are timezone-aware
        now = datetime.now(timezone.utc)
        leave_date = departed_member.leave_date
        if leave_date.tzinfo is None:
            leave_date = leave_date.replace(tzinfo=timezone.utc)
        time_away = now - leave_date
        time_away_str = format_time_away(time_away)

        # Create demonic cultivation-themed reincarnation description
        reincarnation_messages = [
            f"**{member.display_name}** has torn through the veil of death and returned to our demonic sect!",
            f"**{member.display_name}** emerges from the shadow realm, reborn in darkness!",
            f"**{member.display_name}** has conquered death itself and returns with greater power!",
            f"**{member.display_name}** breaks free from the underworld's chains, reincarnated in our sect!",
            f"**{member.display_name}** descends from the blood moon, their soul tempered by otherworldly trials!",
            f"**{member.display_name}** has shattered the boundaries of mortality and returns as a demon reborn!"
        ]

        import random
        description = random.choice(reincarnation_messages)

        cycle_messages = {
            1: [
                "*Their first taste of death and rebirth has forged them anew in demonic fire.*",
                "*Having crossed the threshold of mortality, they return with forbidden knowledge.*",
                "*The cycle of destruction and creation has blessed them with dark enlightenment.*"
            ],
            2: [
                "*Their second dance with death reveals deeper mysteries of the abyss.*",
                "*Twice they have walked the path of shadows and emerged stronger.*",
                "*The dual cycle of annihilation and resurrection marks their ascension.*"
            ],
            3: [
                "*Three times they have conquered death - a true master of reincarnation.*",
                "*The trinity of death and rebirth has granted them unholy wisdom.*",
                "*Thrice blessed by the void, they return as a harbinger of darkness.*"
            ]
        }

        if departed_member.times_left <= 3:
            cycle_desc = random.choice(cycle_messages[departed_member.times_left])
        else:
            cycle_desc = f"*After {get_ordinal(departed_member.times_left)} cycles of death and resurrection, they have transcended mortal understanding.*"

        description += f"\n{cycle_desc}"

        # Add reincarnation details with demonic theme
        reincarnation_details = []
        reincarnation_details.append(f"**Time in Shadow Realm:** {time_away_str}")
        if departed_member.highest_role:
            reincarnation_details.append(f"**Previous Demonic Rank:** {departed_member.highest_role}")
        if departed_member.total_points > 0:
            reincarnation_details.append(f"**Previous Blood Contribution:** {departed_member.total_points:,} points")

        additional_info = "\n".join(reincarnation_details)

        # Add demonic welcome messages
        welcome_messages = [
            f"*Welcome back to the abyss of cultivation, {member.display_name}. May your darkness consume all.*",
            f"*The Heavenly Demon rejoices in your return, {member.display_name}. Let chaos reign.*",
            f"*Your reincarnation strengthens our demonic brotherhood, {member.display_name}.*",
            f"*Rise, {member.display_name}, and let your malevolent qi shake the heavens once more.*",
            f"*The sect's shadow grows deeper with your return, {member.display_name}.*",
            f"*Blood and thunder herald your resurrection, {member.display_name}. Embrace the darkness.*"
        ]

        import random
        additional_info += f"\n\n{random.choice(welcome_messages)}"

        # Create embed
        embed = create_info_embed(
            title=reincarnation_title,
            description=description,
            additional_info=additional_info
        )

        # Add member avatar
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)

        # Add member mention with demonic theme
        embed.add_field(
            name="Reborn Demon",
            value=member.mention,
            inline=True
        )

        # Get reincarnation channel
        channel_config = ChannelConfig(bot.database)
        reincarnation_channel_id = await channel_config.get_reincarnation_channel(member.guild.id)
        logger.info(f"📍 Reincarnation channel ID: {reincarnation_channel_id}")

        if reincarnation_channel_id:
            channel = member.guild.get_channel(reincarnation_channel_id)
            logger.info(f"📱 Found channel: {channel.name if channel else 'None'}")
            if channel and channel.permissions_for(member.guild.me).send_messages:
                await channel.send(content=f"{member.mention}", embed=embed)
                logger.info(f"🔄 Successfully sent reincarnation notification to #{channel.name}")
                return
            else:
                logger.warning(f"⚠️ Cannot send to reincarnation channel #{channel.name if channel else 'NOT_FOUND'}")
        else:
            logger.info("📍 No reincarnation channel configured, using fallback")

        # Fallback to notification channel or general
        logger.info(f"🔄 Using fallback channel for reincarnation notification")
        await send_to_fallback_channel(member.guild, embed, member)

    except Exception as e:
        logger.error(f"❌ Error sending reincarnation notification: {e}")

def generate_funeral_message(display_name, highest_role, total_points, times_left):
    """Generate a demonic cultivation-themed funeral message"""
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

    import random
    return random.choice(messages)

def get_ordinal(number):
    """Convert number to ordinal (1st, 2nd, 3rd, etc.)"""
    if 10 <= number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f"{number}{suffix}"

def format_time_away(time_delta):
    """Format timedelta into human readable string"""
    days = time_delta.days
    hours, remainder = divmod(time_delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        if days == 1:
            return "1 day"
        return f"{days} days"
    elif hours > 0:
        if hours == 1:
            return "1 hour"  
        return f"{hours} hours"
    else:
        if minutes <= 1:
            return "a few moments"
        return f"{minutes} minutes"

# Helper function for fallback channel sending (moved outside of setup_events)
async def send_to_fallback_channel(guild, embed, member=None):
    """Send message to the first available channel as fallback"""
    try:
        logger.info(f"🔄 Attempting fallback notification for guild {guild.name}")

        # Try to find a general or announcements channel first
        preferred_names = ['general', 'announcements', 'leaderboard', 'bot-commands']

        for channel_name in preferred_names:
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if channel and channel.permissions_for(guild.me).send_messages:
                if member:
                    await channel.send(content=f"{member.mention}", embed=embed)
                else:
                    await channel.send(embed=embed)
                logger.info(f"✅ Sent notification to fallback channel #{channel.name}")
                return

        # If no preferred channels found, use the first available text channel
        logger.info(f"📍 Trying first available text channel from {len(guild.text_channels)} channels")
        for channel in guild.text_channels:
            logger.info(f"🔍 Testing channel #{channel.name} - can send: {channel.permissions_for(guild.me).send_messages}")
            if channel.permissions_for(guild.me).send_messages:
                if member:
                    await channel.send(content=f"{member.mention}", embed=embed)
                else:
                    await channel.send(embed=embed)
                logger.info(f"✅ Successfully sent notification to available channel #{channel.name}")
                return

        logger.warning(f"⚠️ No available channels found to send notification in {guild.name}")

    except Exception as e:
        logger.error(f"❌ Error sending to fallback channel: {e}")