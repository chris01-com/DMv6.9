from __future__ import annotations
import logging
import os
import asyncio
from typing import TYPE_CHECKING, Optional

try:
    import discord
    from discord.ext import commands
    from dotenv import load_dotenv
    from aiohttp import web
except ImportError as e:
    raise ImportError(f"Required packages not installed: {e}")

if TYPE_CHECKING:
    try:
        import asyncpg
    except ImportError:
        pass

# Load environment variables
load_dotenv()

# Import bot components
from bot.sql_database import SQLDatabase
from bot.quest_manager import QuestManager
from bot.leaderboard_manager import LeaderboardManager
from bot.config import ChannelConfig
from bot.user_stats import UserStatsManager
from bot.role_rewards import RoleRewardManager
from bot.team_quest_manager import TeamQuestManager
from bot.bounty_manager import BountyManager


from bot.commands import UnifiedBotCommands
from bot.events import setup_events
from bot.welcome_manager import WelcomeManager
from bot.role_commands import setup_role_commands
from bot.mentor_quest_manager import MentorQuestManager
from bot.mentor_commands import MentorCommands
from bot.mentor_channel_manager import MentorChannelManager
from bot.performance_monitor import PerformanceMonitor
from bot.database_optimizer import DatabaseOptimizer
from bot.memory_manager import MemoryManager
from bot.advanced_quest_features import AdvancedQuestFeatures
from bot.enhanced_notifications import EnhancedNotificationSystem
from bot.quest_reminders import QuestReminderSystem
from bot.quest_search import QuestSearchSystem
from bot.quest_recommendations import QuestRecommendationSystem
from bot.quest_favorites import QuestFavoritesSystem
from bot.quest_editing import QuestEditingSystem
from bot.quest_cloning import QuestCloningSystem

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

# Disable aiohttp access logs to prevent health check spam
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

class UnifiedQuestLeaderboardBot(commands.Bot):
    """Unified Quest and Leaderboard Discord Bot"""

    database: Optional['SQLDatabase']
    quest_manager: Optional['QuestManager']
    leaderboard_manager: Optional['LeaderboardManager']

    def __init__(self):
        # Bot intents
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(
            command_prefix='!',  # Fallback prefix for text commands
            intents=intents,
            help_command=None,  # Disable default help command
            case_insensitive=True
        )

        # Initialize managers
        self.database = None
        self.quest_manager = None
        self.leaderboard_manager = None
        self.channel_config = None
        self.user_stats_manager = None
        self.role_reward_manager = None
        self.team_quest_manager = None
        self.bounty_manager = None
        self.welcome_manager = None
        self.mentor_quest_manager = None
        self.mentor_channel_manager = None
        self.performance_monitor = None
        self.database_optimizer = None
        self.memory_manager = None
        self.advanced_quest_features = None
        self.notification_system = None
        self.quest_reminder_system = None
        self.quest_search_system = None
        self.quest_recommendation_system = None
        self.quest_favorites_system = None
        self.quest_editing_system = None
        self.quest_cloning_system = None



    async def setup_hook(self):
        """Initialize bot components"""
        try:
            logger.info("🚀 Starting bot initialization...")

            # Initialize database
            database_url = os.getenv('DATABASE_URL')
            if not database_url:
                logger.error("❌ DATABASE_URL environment variable not set!")
                return

            self.database = SQLDatabase(database_url)
            self.sql_database = self.database  # Add alias for rank manager compatibility
            success = await self.database.initialize()
            if not success:
                logger.error("❌ Failed to initialize database!")
                return

            logger.info("✅ Database initialized successfully")

            # Initialize managers
            self.quest_manager = QuestManager(self.database)
            self.leaderboard_manager = LeaderboardManager(self.database)
            self.leaderboard_manager.bot = self  # Pass bot reference for guild access
            self.channel_config = ChannelConfig(self.database)
            self.user_stats_manager = UserStatsManager(self.database)
            self.role_reward_manager = RoleRewardManager(self, self.leaderboard_manager)
            self.team_quest_manager = TeamQuestManager(self.database)
            self.bounty_manager = BountyManager(self.database)
            self.mentor_quest_manager = MentorQuestManager(self.database)
            self.database.bot = self  # type: ignore  # Pass bot reference to database for mentor notifications
            self.mentor_channel_manager = MentorChannelManager(self.database)
            self.welcome_manager = WelcomeManager(self.database, self.quest_manager, self.mentor_channel_manager)

            # Initialize performance systems
            self.performance_monitor = PerformanceMonitor(self)
            self.database_optimizer = DatabaseOptimizer(self.database)
            self.memory_manager = MemoryManager(self)
            self.advanced_quest_features = AdvancedQuestFeatures(self.database, self.quest_manager)
            self.notification_system = EnhancedNotificationSystem(self, self.database)

            # Initialize quest enhancement systems
            self.quest_reminder_system = QuestReminderSystem(self, self.database, self.notification_system)
            self.quest_search_system = QuestSearchSystem(self.database, self.quest_manager)
            self.quest_recommendation_system = QuestRecommendationSystem(self.database, self.quest_manager)
            self.quest_favorites_system = QuestFavoritesSystem(self.database, self.quest_manager)
            self.quest_editing_system = QuestEditingSystem(self.database, self.quest_manager, self.notification_system)
            self.quest_cloning_system = QuestCloningSystem(self.database, self.quest_manager)

            # Start performance monitoring
            self.performance_monitor.start_monitoring()
            self.memory_manager.start_memory_management()

            # Initialize advanced quest features
            await self.advanced_quest_features.initialize_quest_features()

            # Initialize notification system
            await self.notification_system.initialize_notifications()

            # Optimize database
            await self.database_optimizer.create_performance_indexes()
            await self.database_optimizer.optimize_quest_queries()
            await self.database_optimizer.analyze_table_statistics()



            # Initialize team quest database tables
            await self.team_quest_manager.initialize_database()

            # Initialize mentor quest database tables
            await self.mentor_quest_manager.initialize_mentor_quest_tables()

            # Initialize welcome automation tables
            await self.welcome_manager.initialize_welcome_tables()

            # Initialize quest enhancement systems
            await self.quest_reminder_system.initialize_reminder_system()
            await self.quest_favorites_system.initialize_favorites_system()
            await self.quest_editing_system.initialize_editing_system()
            await self.quest_cloning_system.initialize_cloning_system()
            logger.info("✅ Quest enhancement systems initialized")



            logger.info("✅ All managers initialized")

            # Add command cog
            await self.add_cog(UnifiedBotCommands(
                self,
                self.quest_manager,
                self.channel_config,
                self.user_stats_manager,
                self.leaderboard_manager,
                self.role_reward_manager,
                self.team_quest_manager,
                self.bounty_manager,

            ))

            logger.info("✅ Commands loaded")

            # Setup events
            setup_events(self, self.leaderboard_manager, self.welcome_manager)
            logger.info("✅ Events configured")

            # Setup role commands
            setup_role_commands(self, self.role_reward_manager)
            logger.info("✅ Role commands configured")

            # Add mentor system commands
            await self.add_cog(MentorCommands(self, self.database, self.mentor_quest_manager))
            logger.info("✅ Mentor system commands loaded")

            # Add admin performance commands
            from bot.admin_performance_commands import AdminPerformanceCommands
            await self.add_cog(AdminPerformanceCommands(self))
            logger.info("✅ Admin performance commands loaded")

            # Add enhanced quest commands
            from bot.enhanced_quest_commands import EnhancedQuestCommands
            await self.add_cog(EnhancedQuestCommands(self))
            logger.info("✅ Enhanced quest commands loaded")

            # Add server analyzer commands
            from bot.server_analyzer import ServerAnalyzer
            await self.add_cog(ServerAnalyzer(self))
            logger.info("✅ Server analyzer commands loaded")

            # Add rank progress commands
            from bot.rank_progress_command import RankProgressCommands
            await self.add_cog(RankProgressCommands(self))
            logger.info("✅ Rank progress commands loaded")

            # Add rank management system
            from bot.rank_commands import RankCommands
            from bot.rank_events import RankEvents
            await self.add_cog(RankCommands(self))
            await self.add_cog(RankEvents(self))
            logger.info("✅ Rank management system loaded")





            # Debug: Log all registered commands before syncing
            registered_commands = self.tree.get_commands()
            logger.info(f"🔍 Total commands registered before sync: {len(registered_commands)}")

            # Log mentor commands specifically
            mentor_commands = [cmd for cmd in registered_commands if 'mentor' in cmd.name.lower() or 'student' in cmd.name.lower()]
            logger.info(f"🎓 Mentor commands found: {len(mentor_commands)}")
            for cmd in mentor_commands:
                logger.info(f"  🎓 Mentor Command: /{cmd.name} - {cmd.description}")

            # Log first 10 overall commands
            for cmd in registered_commands[:10]:  # Show first 10 commands
                logger.info(f"  📝 Command: /{cmd.name} - {cmd.description[:50]}...")

            # Start welcome automation background task
            self.loop.create_task(self._welcome_reminder_task())
            logger.info("✅ Welcome automation background task started")

            # Sync slash commands globally with timeout and better error handling
            try:
                logger.info("🔄 Syncing slash commands globally...")
                
                # Add timeout to prevent hanging
                synced = await asyncio.wait_for(self.tree.sync(), timeout=30.0)
                logger.info(f"✅ Synced {len(synced)} slash commands globally")
                
                # Verify all commands are synced
                if len(synced) != len(registered_commands):
                    logger.warning(f"⚠️ Command count mismatch: {len(synced)} synced vs {len(registered_commands)} registered")
                    
                # Also sync for main guild for immediate availability
                if self.guilds:
                    main_guild = self.guilds[0]  # Use first guild as main
                    try:
                        guild_synced = await asyncio.wait_for(self.tree.sync(guild=main_guild), timeout=15.0)
                        logger.info(f"✅ Guild sync: {len(guild_synced)} commands for {main_guild.name}")
                    except asyncio.TimeoutError:
                        logger.warning(f"⚠️ Guild sync timeout for {main_guild.name}")
                    except Exception as guild_error:
                        logger.warning(f"⚠️ Failed guild sync for {main_guild.name}: {guild_error}")

            except asyncio.TimeoutError:
                logger.error("❌ Global sync timed out after 30 seconds")
                # Try guild-specific sync as fallback
                logger.info("🔄 Attempting guild-specific sync as fallback...")
                for guild in self.guilds:
                    try:
                        guild_synced = await asyncio.wait_for(self.tree.sync(guild=guild), timeout=15.0)
                        logger.info(f"✅ Fallback guild sync: {len(guild_synced)} commands for {guild.name}")
                        break  # Stop after first successful guild sync
                    except Exception as guild_error:
                        logger.warning(f"⚠️ Guild sync failed for {guild.name}: {guild_error}")
                        
            except Exception as e:
                logger.error(f"❌ Failed to sync commands: {e}")
                # Try clearing and re-syncing as last resort
                try:
                    logger.info("🔄 Attempting clear and re-sync as fallback...")
                    self.tree.clear_commands(guild=None)
                    await asyncio.sleep(2)  # Longer delay after clearing
                    fallback_synced = await asyncio.wait_for(self.tree.sync(), timeout=20.0)
                    logger.info(f"✅ Fallback sync successful: {len(fallback_synced)} commands")
                except Exception as alt_error:
                    logger.error(f"❌ All sync methods failed: {alt_error}")
                    logger.info("⚠️ Bot will continue without full command sync - some commands may show as 'Unknown Integration'")

            logger.info("🎉 Bot initialization complete!")

        except Exception as e:
            logger.error(f"❌ Error during setup: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f"✅ {self.user} is now online and ready!")
        logger.info(f"📊 Connected to {len(self.guilds)} guilds")
        logger.info(f"👥 Serving {sum(len(guild.members) for guild in self.guilds)} total users")

        # Set bot status
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="quests and leaderboards"
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

        # Initialize leaderboards for all guilds
        for guild in self.guilds:
            try:
                logger.info(f"🔄 Initializing leaderboard for {guild.name}")
                for member in guild.members:
                    if not member.bot and self.leaderboard_manager:
                        await self.leaderboard_manager.add_member(
                            guild.id, member.id, member.display_name
                        )
                logger.info(f"✅ Leaderboard initialized for {guild.name}")
            except Exception as e:
                logger.error(f"❌ Error initializing {guild.name}: {e}")

    async def on_guild_join(self, guild):
        """Called when bot joins a new guild"""
        logger.info(f"🆕 Joined new guild: {guild.name} (ID: {guild.id})")

        # Initialize leaderboard for new guild
        try:
            member_count = 0
            for member in guild.members:
                if not member.bot and self.leaderboard_manager:
                    await self.leaderboard_manager.add_member(
                        guild.id, member.id, member.display_name
                    )
                    member_count += 1

            logger.info(f"✅ Initialized leaderboard for {guild.name} with {member_count} members")

        except Exception as e:
            logger.error(f"❌ Error initializing new guild {guild.name}: {e}")

    async def on_guild_remove(self, guild):
        """Called when bot leaves a guild"""
        logger.info(f"👋 Left guild: {guild.name} (ID: {guild.id})")

        # Cleanup role reward tasks
        if self.role_reward_manager:
            await self.role_reward_manager.cleanup_guild(guild.id)


    async def close(self):
        """Cleanup when bot shuts down"""
        logger.info("🛑 Bot shutting down...")

        # Stop performance monitoring
        if self.performance_monitor:
            self.performance_monitor.stop_monitoring()
        if self.memory_manager:
            self.memory_manager.stop_memory_management()
        if self.notification_system:
            self.notification_system.stop_processing()

        # Cancel role reward tasks
        if self.role_reward_manager:
            for guild_id in list(self.role_reward_manager.active_tasks.keys()):
                await self.role_reward_manager.cleanup_guild(guild_id)


        # Close database connections
        if self.database and self.database.pool:
            await self.database.pool.close()
            logger.info("✅ Database connections closed")

        await super().close()
        logger.info("✅ Bot shutdown complete")

    async def _welcome_reminder_task(self):
        """Background task for welcome automation reminders"""
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                if self.welcome_manager:
                    await self.welcome_manager.send_48_hour_reminders(self)
                    logger.debug("🔄 Welcome reminder check completed")

                # Run every 2 hours
                await asyncio.sleep(7200)

            except Exception as e:
                logger.error(f"❌ Error in welcome reminder task: {e}")
                await asyncio.sleep(7200)  # Continue after error

# Create bot instance
bot = UnifiedQuestLeaderboardBot()

# Error handlers
@bot.event
async def on_error(event, *args, **kwargs):
    """Global error handler"""
    logger.error(f"❌ Error in event {event}: {args}")
    import traceback
    logger.error(f"Full traceback: {traceback.format_exc()}")

@bot.event
async def on_command_error(ctx, error):
    """Command error handler"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore unknown commands

    logger.error(f"❌ Command error in {ctx.command}: {error}")

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.", ephemeral=False)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing required argument: {error.param}", ephemeral=False)
    else:
        await ctx.send("An error occurred while processing your command.", ephemeral=False)

# Health check server for Render.com
async def health_check(request):
    """Simple health check endpoint"""
    return web.Response(text="Discord Bot is running!")

async def start_health_server():
    """Start HTTP server for health checks"""
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)

    port = int(os.getenv('PORT', 5000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"✅ Health check server started on port {port}")

# Run the bot
async def main():
    """Main function to run the bot"""
    try:
        # Start health check server for Render
        await start_health_server()

        # Get bot token
        token = os.getenv('DISCORD_TOKEN')
        if not token:
            logger.error("❌ DISCORD_TOKEN environment variable not set!")
            return

        # Start the bot
        await bot.start(token)

    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
    finally:
        await bot.close()

if __name__ == "__main__":
    # Create event loop and run
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Application terminated by user")
    except Exception as e:
        logger.error(f"❌ Application error: {e}")