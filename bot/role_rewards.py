import discord
import logging
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger(__name__)

class RoleRewardManager:
    """Enhanced role reward manager with improved logging and error handling"""

    def __init__(self, bot, leaderboard_manager):
        self.bot = bot
        self.leaderboard_manager = leaderboard_manager
        self.role_rewards = {}  # guild_id -> {role_id: points_per_interval}
        self.reward_intervals = {}  # guild_id -> interval_hours
        self.last_reward_time = {}  # guild_id -> {user_id: last_reward_datetime}
        self.active_tasks = {}  # guild_id -> asyncio.Task
        
        logger.info("✅ Role reward manager initialized")

    async def trigger_leaderboard_updates(self, guild_id):
        """Enhanced leaderboard update trigger with better error handling"""
        try:
            # Import here to avoid circular imports
            import bot.commands as commands_module

            guild_id = int(guild_id)
            logger.info(f"🔄 Triggering leaderboard updates for guild {guild_id}")

            # Find and update all active leaderboard views for this guild
            if hasattr(commands_module, 'active_leaderboard_views'):
                views_updated = 0
                failed_updates = 0
                
                for view in commands_module.active_leaderboard_views[:]:  # Create a copy to iterate safely
                    if view.guild_id == guild_id:
                        try:
                            await view.auto_update_leaderboard()
                            views_updated += 1
                            logger.debug(f"✅ Updated leaderboard view for guild {guild_id}")
                        except Exception as e:
                            logger.error(f"❌ Failed to update leaderboard view: {e}")
                            failed_updates += 1
                            # Remove failed view from active list
                            try:
                                commands_module.active_leaderboard_views.remove(view)
                            except ValueError:
                                pass  # Already removed

                logger.info(f"✅ Leaderboard updates complete for guild {guild_id} - Updated: {views_updated}, Failed: {failed_updates}")

                # Also trigger the update function directly
                await commands_module.update_active_leaderboards(guild_id)
            else:
                logger.warning("⚠️ No active_leaderboard_views found in commands module")

        except Exception as e:
            logger.error(f"❌ Error triggering leaderboard updates: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
    
    async def check_member_rank_eligibility(self, member, points):
        """Enhanced rank eligibility check with better logic"""
        try:
            from bot.utils import get_rank_title_by_points
            rank_title = get_rank_title_by_points(points, member)
            
            logger.debug(f"📊 Member {member.display_name} has {points} points and rank {rank_title}")
            return rank_title
            
        except Exception as e:
            logger.error(f"❌ Error checking rank eligibility for {member.display_name}: {e}")
            return "Unknown"

    async def setup_role_rewards(self, guild_id, role_rewards_config, interval_hours=24):
        """Setup automatic role rewards for a guild"""
        try:
            self.role_rewards[guild_id] = role_rewards_config
            self.reward_intervals[guild_id] = interval_hours
            
            # Start the reward task for this guild
            if guild_id in self.active_tasks:
                self.active_tasks[guild_id].cancel()
            
            self.active_tasks[guild_id] = asyncio.create_task(
                self._role_reward_loop(guild_id)
            )
            
            logger.info(f"✅ Role rewards configured for guild {guild_id} with {interval_hours}h interval")
            
        except Exception as e:
            logger.error(f"❌ Error setting up role rewards for guild {guild_id}: {e}")

    async def _role_reward_loop(self, guild_id):
        """Background task for distributing role rewards"""
        try:
            while True:
                await asyncio.sleep(3600)  # Check every hour
                
                if guild_id not in self.role_rewards:
                    continue
                
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    logger.warning(f"⚠️ Guild {guild_id} not found for role rewards")
                    continue
                
                current_time = datetime.now()
                interval_hours = self.reward_intervals.get(guild_id, 24)
                
                # Initialize last reward time for guild if not exists
                if guild_id not in self.last_reward_time:
                    self.last_reward_time[guild_id] = {}
                
                members_rewarded = 0
                
                for member in guild.members:
                    if member.bot:
                        continue
                    
                    # Check if enough time has passed since last reward
                    last_reward = self.last_reward_time[guild_id].get(member.id)
                    if last_reward:
                        time_since_last = current_time - last_reward
                        if time_since_last < timedelta(hours=interval_hours):
                            continue
                    
                    # Calculate points for this member's roles
                    total_points = 0
                    for role in member.roles:
                        if role.id in self.role_rewards[guild_id]:
                            total_points += self.role_rewards[guild_id][role.id]
                    
                    if total_points > 0:
                        # Award points
                        success = await self.leaderboard_manager.update_points(
                            guild_id, member.id, total_points, member.display_name
                        )
                        
                        if success:
                            self.last_reward_time[guild_id][member.id] = current_time
                            members_rewarded += 1
                            logger.debug(f"✅ Awarded {total_points} role points to {member.display_name}")
                
                if members_rewarded > 0:
                    logger.info(f"✅ Awarded role rewards to {members_rewarded} members in guild {guild_id}")
                    # Trigger leaderboard updates
                    await self.trigger_leaderboard_updates(guild_id)
                
        except asyncio.CancelledError:
            logger.info(f"ℹ️ Role reward loop cancelled for guild {guild_id}")
        except Exception as e:
            logger.error(f"❌ Error in role reward loop for guild {guild_id}: {e}")

    async def add_role_reward(self, guild_id, role_id, points_per_interval):
        """Add or update role reward configuration"""
        try:
            if guild_id not in self.role_rewards:
                self.role_rewards[guild_id] = {}
            
            self.role_rewards[guild_id][role_id] = points_per_interval
            logger.info(f"✅ Added role reward: {points_per_interval} points for role {role_id} in guild {guild_id}")
            
        except Exception as e:
            logger.error(f"❌ Error adding role reward: {e}")

    async def remove_role_reward(self, guild_id, role_id):
        """Remove role reward configuration"""
        try:
            if guild_id in self.role_rewards and role_id in self.role_rewards[guild_id]:
                del self.role_rewards[guild_id][role_id]
                logger.info(f"✅ Removed role reward for role {role_id} in guild {guild_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"❌ Error removing role reward: {e}")
            return False

    async def get_role_rewards(self, guild_id):
        """Get role reward configuration for a guild"""
        return self.role_rewards.get(guild_id, {})

    async def set_reward_interval(self, guild_id, interval_hours):
        """Set reward interval for a guild"""
        try:
            self.reward_intervals[guild_id] = interval_hours
            logger.info(f"✅ Set reward interval to {interval_hours} hours for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"❌ Error setting reward interval: {e}")

    async def get_member_last_reward_time(self, guild_id, user_id):
        """Get the last time a member received role rewards"""
        if guild_id in self.last_reward_time and user_id in self.last_reward_time[guild_id]:
            return self.last_reward_time[guild_id][user_id]
        return None

    async def calculate_member_role_points(self, member, guild_id):
        """Calculate how many points a member would get from their roles"""
        if guild_id not in self.role_rewards:
            return 0
        
        total_points = 0
        for role in member.roles:
            if role.id in self.role_rewards[guild_id]:
                total_points += self.role_rewards[guild_id][role.id]
        
        return total_points

    async def force_role_rewards(self, guild_id, user_id=None):
        """Force role reward distribution for a guild or specific user"""
        try:
            if guild_id not in self.role_rewards:
                logger.warning(f"⚠️ No role rewards configured for guild {guild_id}")
                return 0
            
            guild = self.bot.get_guild(guild_id)
            if not guild:
                logger.error(f"❌ Guild {guild_id} not found")
                return 0
            
            current_time = datetime.now()
            members_rewarded = 0
            
            # Initialize last reward time for guild if not exists
            if guild_id not in self.last_reward_time:
                self.last_reward_time[guild_id] = {}
            
            target_members = [guild.get_member(user_id)] if user_id else guild.members
            
            for member in target_members:
                if not member or member.bot:
                    continue
                
                # Calculate points for this member's roles
                total_points = await self.calculate_member_role_points(member, guild_id)
                
                if total_points > 0:
                    # Award points
                    success = await self.leaderboard_manager.update_points(
                        guild_id, member.id, total_points, member.display_name
                    )
                    
                    if success:
                        self.last_reward_time[guild_id][member.id] = current_time
                        members_rewarded += 1
                        logger.info(f"✅ Force awarded {total_points} role points to {member.display_name}")
            
            if members_rewarded > 0:
                # Trigger leaderboard updates
                await self.trigger_leaderboard_updates(guild_id)
            
            return members_rewarded
            
        except Exception as e:
            logger.error(f"❌ Error in force role rewards: {e}")
            return 0

    async def cleanup_guild(self, guild_id):
        """Cleanup role reward data for a guild"""
        try:
            # Cancel active task
            if guild_id in self.active_tasks:
                self.active_tasks[guild_id].cancel()
                del self.active_tasks[guild_id]
            
            # Clear data
            if guild_id in self.role_rewards:
                del self.role_rewards[guild_id]
            
            if guild_id in self.reward_intervals:
                del self.reward_intervals[guild_id]
            
            if guild_id in self.last_reward_time:
                del self.last_reward_time[guild_id]
            
            logger.info(f"✅ Cleaned up role reward data for guild {guild_id}")
            
        except Exception as e:
            logger.error(f"❌ Error cleaning up guild {guild_id}: {e}")