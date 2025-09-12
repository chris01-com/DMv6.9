import asyncio
import discord
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class EnhancedNotificationSystem:
    """Enhanced notification system with user preferences and smart notifications"""
    
    def __init__(self, bot, database):
        self.bot = bot
        self.database = database
        self.notification_queue = asyncio.Queue()
        self.processing_task = None
    
    async def initialize_notifications(self):
        """Initialize notification system"""
        try:
            async with self.database.pool.acquire() as conn:
                # User notification preferences
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS notification_preferences (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        quest_completions BOOLEAN DEFAULT TRUE,
                        rank_promotions BOOLEAN DEFAULT TRUE,
                        mentor_assignments BOOLEAN DEFAULT TRUE,
                        leaderboard_changes BOOLEAN DEFAULT FALSE,
                        team_quest_invites BOOLEAN DEFAULT TRUE,
                        bounty_notifications BOOLEAN DEFAULT TRUE,
                        dm_notifications BOOLEAN DEFAULT TRUE,
                        channel_notifications BOOLEAN DEFAULT TRUE,
                        digest_frequency VARCHAR(20) DEFAULT 'daily',
                        quiet_hours_start INTEGER DEFAULT 22,
                        quiet_hours_end INTEGER DEFAULT 8,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, guild_id)
                    )
                ''')
                
                # Notification history
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS notification_history (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        notification_type VARCHAR(50) NOT NULL,
                        title VARCHAR(255),
                        content TEXT,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        delivery_method VARCHAR(20) DEFAULT 'dm',
                        read_at TIMESTAMP
                    )
                ''')
                
                # Notification digests
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS notification_digests (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        digest_date DATE NOT NULL,
                        quest_completions INTEGER DEFAULT 0,
                        rank_changes INTEGER DEFAULT 0,
                        points_earned INTEGER DEFAULT 0,
                        new_quests INTEGER DEFAULT 0,
                        sent_at TIMESTAMP,
                        PRIMARY KEY (user_id, guild_id, digest_date)
                    )
                ''')
                
            logger.info("✅ Enhanced notification system initialized")
            
            # Start notification processing
            self.processing_task = asyncio.create_task(self._process_notifications())
            
        except Exception as e:
            logger.error(f"❌ Error initializing notifications: {e}")
    
    async def _process_notifications(self):
        """Process notification queue"""
        while True:
            try:
                # Get notification from queue
                notification = await self.notification_queue.get()
                
                # Process the notification
                await self._send_notification(notification)
                
                # Mark task as done
                self.notification_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error processing notification: {e}")
                await asyncio.sleep(1)
    
    async def queue_notification(self, user_id: int, guild_id: int, notification_type: str,
                               title: str, content: str, priority: str = 'normal'):
        """Queue a notification for processing"""
        notification = {
            'user_id': user_id,
            'guild_id': guild_id,
            'type': notification_type,
            'title': title,
            'content': content,
            'priority': priority,
            'created_at': datetime.now()
        }
        
        await self.notification_queue.put(notification)
    
    async def _send_notification(self, notification: Dict):
        """Send a notification based on user preferences"""
        try:
            user_id = notification['user_id']
            guild_id = notification['guild_id']
            
            # Get user preferences
            prefs = await self._get_user_preferences(user_id, guild_id)
            
            # Check if user wants this type of notification
            notification_type = notification['type']
            if not self._should_send_notification(prefs, notification_type):
                return
            
            # Check quiet hours
            if self._is_quiet_hours(prefs):
                # Queue for later or add to digest
                await self._queue_for_digest(notification)
                return
            
            # Get user and guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            user = guild.get_member(user_id)
            if not user:
                return
            
            # Create embed
            embed = discord.Embed(
                title=notification['title'],
                description=notification['content'],
                color=self._get_notification_color(notification_type),
                timestamp=notification['created_at']
            )
            
            # Add footer with guild info
            embed.set_footer(text=f"From {guild.name}", icon_url=guild.icon.url if guild.icon else None)
            
            # Send notification
            sent = False
            if prefs.get('dm_notifications', True):
                try:
                    await user.send(embed=embed)
                    sent = True
                except discord.Forbidden:
                    logger.warning(f"⚠️ Cannot send DM to {user.display_name}")
            
            # Fallback to channel notification if DM failed
            if not sent and prefs.get('channel_notifications', True):
                # Find appropriate channel
                channel = await self._find_notification_channel(guild, user)
                if channel:
                    embed.description = f"{user.mention} {embed.description}"
                    await channel.send(embed=embed)
                    sent = True
            
            # Record notification history
            if sent:
                await self._record_notification_history(notification, 'dm' if prefs.get('dm_notifications', True) else 'channel')
            
        except Exception as e:
            logger.error(f"❌ Error sending notification: {e}")
    
    async def _get_user_preferences(self, user_id: int, guild_id: int) -> Dict:
        """Get user notification preferences"""
        try:
            async with self.database.pool.acquire() as conn:
                prefs = await conn.fetchrow('''
                    SELECT * FROM notification_preferences 
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)
                
                if prefs:
                    return dict(prefs)
                else:
                    # Return default preferences
                    return {
                        'quest_completions': True,
                        'rank_promotions': True,
                        'mentor_assignments': True,
                        'leaderboard_changes': False,
                        'team_quest_invites': True,
                        'bounty_notifications': True,
                        'dm_notifications': True,
                        'channel_notifications': True,
                        'digest_frequency': 'daily',
                        'quiet_hours_start': 22,
                        'quiet_hours_end': 8
                    }
        except Exception as e:
            logger.error(f"❌ Error getting user preferences: {e}")
            return {}
    
    def _should_send_notification(self, prefs: Dict, notification_type: str) -> bool:
        """Check if notification should be sent based on preferences"""
        type_mapping = {
            'quest_completion': 'quest_completions',
            'rank_promotion': 'rank_promotions',
            'mentor_assignment': 'mentor_assignments',
            'leaderboard_change': 'leaderboard_changes',
            'team_quest_invite': 'team_quest_invites',
            'bounty_notification': 'bounty_notifications'
        }
        
        pref_key = type_mapping.get(notification_type, 'quest_completions')
        return prefs.get(pref_key, True)
    
    def _is_quiet_hours(self, prefs: Dict) -> bool:
        """Check if current time is within user's quiet hours"""
        try:
            current_hour = datetime.now().hour
            start_hour = prefs.get('quiet_hours_start', 22)
            end_hour = prefs.get('quiet_hours_end', 8)
            
            if start_hour <= end_hour:
                # Same day quiet hours (e.g., 14:00 to 16:00)
                return start_hour <= current_hour <= end_hour
            else:
                # Overnight quiet hours (e.g., 22:00 to 8:00)
                return current_hour >= start_hour or current_hour <= end_hour
        except:
            return False
    
    def _get_notification_color(self, notification_type: str) -> discord.Color:
        """Get color for notification based on type"""
        colors = {
            'quest_completion': discord.Color.green(),
            'rank_promotion': discord.Color.gold(),
            'mentor_assignment': discord.Color.blue(),
            'leaderboard_change': discord.Color.purple(),
            'team_quest_invite': discord.Color.orange(),
            'bounty_notification': discord.Color.red(),
            'system': discord.Color.grey()
        }
        return colors.get(notification_type, discord.Color.blue())
    
    async def _find_notification_channel(self, guild: discord.Guild, user: discord.Member) -> Optional[discord.TextChannel]:
        """Find appropriate channel for notifications"""
        # Look for common notification channel names
        channel_names = ['notifications', 'bot-notifications', 'general', 'announcements']
        
        for name in channel_names:
            channel = discord.utils.get(guild.text_channels, name=name)
            if channel and channel.permissions_for(guild.me).send_messages:
                return channel
        
        # Fallback to first available channel
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                return channel
        
        return None
    
    async def _record_notification_history(self, notification: Dict, delivery_method: str):
        """Record notification in history"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO notification_history 
                    (user_id, guild_id, notification_type, title, content, delivery_method)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', notification['user_id'], notification['guild_id'], 
                     notification['type'], notification['title'], 
                     notification['content'], delivery_method)
        except Exception as e:
            logger.error(f"❌ Error recording notification history: {e}")
    
    async def _queue_for_digest(self, notification: Dict):
        """Queue notification for daily digest"""
        try:
            user_id = notification['user_id']
            guild_id = notification['guild_id']
            today = datetime.now().date()
            
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO notification_digests (user_id, guild_id, digest_date)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, guild_id, digest_date) DO NOTHING
                ''', user_id, guild_id, today)
                
                # Update digest counters based on notification type
                if notification['type'] == 'quest_completion':
                    await conn.execute('''
                        UPDATE notification_digests 
                        SET quest_completions = quest_completions + 1
                        WHERE user_id = $1 AND guild_id = $2 AND digest_date = $3
                    ''', user_id, guild_id, today)
                elif notification['type'] == 'rank_promotion':
                    await conn.execute('''
                        UPDATE notification_digests 
                        SET rank_changes = rank_changes + 1
                        WHERE user_id = $1 AND guild_id = $2 AND digest_date = $3
                    ''', user_id, guild_id, today)
                    
        except Exception as e:
            logger.error(f"❌ Error queuing for digest: {e}")
    
    async def send_daily_digests(self):
        """Send daily notification digests"""
        try:
            yesterday = (datetime.now() - timedelta(days=1)).date()
            
            async with self.database.pool.acquire() as conn:
                digests = await conn.fetch('''
                    SELECT * FROM notification_digests 
                    WHERE digest_date = $1 AND sent_at IS NULL
                    AND (quest_completions > 0 OR rank_changes > 0 OR points_earned > 0 OR new_quests > 0)
                ''', yesterday)
                
                for digest in digests:
                    await self._send_digest(digest)
                    
                    # Mark as sent
                    await conn.execute('''
                        UPDATE notification_digests 
                        SET sent_at = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2 AND digest_date = $3
                    ''', digest['user_id'], digest['guild_id'], digest['digest_date'])
                    
        except Exception as e:
            logger.error(f"❌ Error sending daily digests: {e}")
    
    async def _send_digest(self, digest: Dict):
        """Send individual digest to user"""
        try:
            guild = self.bot.get_guild(digest['guild_id'])
            if not guild:
                return
                
            user = guild.get_member(digest['user_id'])
            if not user:
                return
            
            embed = discord.Embed(
                title="📅 Daily Activity Summary",
                description=f"Here's your activity summary for {digest['digest_date']}",
                color=discord.Color.blue()
            )
            
            if digest['quest_completions'] > 0:
                embed.add_field(
                    name="🎯 Quest Completions",
                    value=f"{digest['quest_completions']} quests completed",
                    inline=True
                )
            
            if digest['rank_changes'] > 0:
                embed.add_field(
                    name="⬆️ Rank Changes",
                    value=f"{digest['rank_changes']} rank promotions",
                    inline=True
                )
            
            if digest['points_earned'] > 0:
                embed.add_field(
                    name="💎 Points Earned",
                    value=f"{digest['points_earned']} points",
                    inline=True
                )
            
            embed.set_footer(text=f"From {guild.name}")
            
            await user.send(embed=embed)
            
        except Exception as e:
            logger.error(f"❌ Error sending digest: {e}")
    
    async def update_user_preferences(self, user_id: int, guild_id: int, **preferences):
        """Update user notification preferences"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get current preferences or create new
                await conn.execute('''
                    INSERT INTO notification_preferences (user_id, guild_id)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id, guild_id) DO NOTHING
                ''', user_id, guild_id)
                
                # Update specific preferences
                for key, value in preferences.items():
                    if hasattr(value, '__bool__'):  # Boolean values
                        await conn.execute(f'''
                            UPDATE notification_preferences 
                            SET {key} = $3
                            WHERE user_id = $1 AND guild_id = $2
                        ''', user_id, guild_id, value)
                    else:  # String/integer values
                        await conn.execute(f'''
                            UPDATE notification_preferences 
                            SET {key} = $3
                            WHERE user_id = $1 AND guild_id = $2
                        ''', user_id, guild_id, value)
                        
            logger.info(f"✅ Updated notification preferences for user {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Error updating preferences: {e}")
    
    def stop_processing(self):
        """Stop notification processing"""
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
        logger.info("🔔 Notification processing stopped")