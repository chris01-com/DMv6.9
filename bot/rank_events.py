import discord
from discord.ext import commands
from datetime import datetime, timedelta
from bot.utils import SPECIAL_ROLES


class RankEvents(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rank_manager = None
        
    async def cog_load(self):
        """Initialize rank manager when cog loads"""
        pass  # Will be initialized in get_rank_manager()
    
    async def get_rank_manager(self):
        """Get or create rank manager instance"""
        if not self.rank_manager and hasattr(self.bot, 'sql_database') and self.bot.sql_database:
            from bot.rank_manager import RankManager
            self.rank_manager = RankManager(self.bot.sql_database)
            # Initialize tables
            if not getattr(self.rank_manager, '_initialized', False):
                await self.rank_manager.initialize_tables()
        return self.rank_manager
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Monitor role changes for high rank roles"""
        rank_manager = await self.get_rank_manager()
        if not rank_manager:
            return
        
        # Get high rank roles that were added or removed
        before_roles = set(role.id for role in before.roles)
        after_roles = set(role.id for role in after.roles)
        
        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles
        
        # Handle added high rank roles
        for role_id in added_roles:
            if rank_manager.is_high_rank_role(role_id):
                await self.handle_role_added(after, role_id)
        
        # Handle removed high rank roles
        for role_id in removed_roles:
            if rank_manager.is_high_rank_role(role_id):
                await self.handle_role_removed(after, role_id)
    
    async def handle_role_added(self, member: discord.Member, role_id: int):
        """Handle when a high rank role is added to a member"""
        try:
            rank_manager = await self.get_rank_manager()
            if not rank_manager:
                return
            
            # Try to find who gave the role from audit logs
            moderator_id = await self.get_role_moderator(member.guild, member.id, role_id)
                
            # Track the role assignment
            await rank_manager.track_role_assignment(member.guild.id, member.id, role_id)
            
            # Log the activity with moderator info
            await rank_manager.log_hr_activity(
                member.guild.id, 
                member.id, 
                role_id, 
                "ADDED", 
                "MANUAL",
                moderator_id
            )
            
            # Check if role limit is exceeded and enforce if needed (excluding the user who just got the role)
            removed_member = await rank_manager.enforce_role_limit(member.guild, role_id, member.id)
            

            
            # Notify if someone was removed due to limit
            if removed_member:
                role_name = SPECIAL_ROLES.get(role_id, "Unknown Role")
                print(f"Role limit enforced: Removed {removed_member.display_name} from {role_name} to make room for {member.display_name}")
                
                # Try to DM the removed member
                try:
                    embed = discord.Embed(
                        title="🔴 High Rank Role Removed",
                        description=f"Your **{role_name}** role in **{member.guild.name}** was automatically removed because the role reached its member limit when it was assigned to another member.",
                        color=0xFF0000
                    )
                    embed.add_field(
                        name="Reason", 
                        value="Role member limit exceeded - newest assignment removed", 
                        inline=False
                    )
                    await removed_member.send(embed=embed)
                except:
                    pass  # Ignore if DM fails
        
        except Exception as e:
            print(f"Error handling role addition: {e}")
    
    async def handle_role_removed(self, member: discord.Member, role_id: int):
        """Handle when a high rank role is removed from a member"""
        try:
            rank_manager = await self.get_rank_manager()
            if not rank_manager:
                return
                
            # Remove role assignment tracking
            await rank_manager.remove_role_assignment(member.guild.id, member.id, role_id)
            
            # Log the activity (only if not already logged by enforcement)
            recent_activity = await rank_manager.get_recent_hr_activity(member.guild.id, 1)
            if not (recent_activity and 
                   recent_activity[0]['user_id'] == member.id and 
                   recent_activity[0]['role_id'] == role_id and 
                   recent_activity[0]['action'] == "REMOVED"):
                await rank_manager.log_hr_activity(
                    member.guild.id, 
                    member.id, 
                    role_id, 
                    "REMOVED", 
                    "MANUAL"
                )
            

        
        except Exception as e:
            print(f"Error handling role removal: {e}")
    
    async def get_role_moderator(self, guild: discord.Guild, user_id: int, role_id: int):
        """Try to find who gave the role from audit logs"""
        try:
            # Check audit logs for recent role updates
            async for entry in guild.audit_logs(action=discord.AuditLogAction.member_role_update, limit=10):
                # Check if this entry is for our user and happened recently (within last minute)
                if (entry.target.id == user_id and 
                    entry.created_at > discord.utils.utcnow() - datetime.timedelta(minutes=1)):
                    
                    # Check if the role was added in this entry
                    if hasattr(entry.changes, 'after') and hasattr(entry.changes, 'before'):
                        for change in entry.changes:
                            if change.key == 'roles':
                                before_roles = {role.id for role in change.before} if change.before else set()
                                after_roles = {role.id for role in change.after} if change.after else set()
                                
                                # Check if our role was added
                                if role_id in after_roles and role_id not in before_roles:
                                    return entry.user.id
            return None
        except (discord.Forbidden, discord.HTTPException):
            # Bot doesn't have audit log permissions or other error
            return None
    


async def setup(bot):
    await bot.add_cog(RankEvents(bot))