import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import discord

logger = logging.getLogger(__name__)

class QuestReminderSystem:
    """Smart reminder system for accepted but incomplete quests"""
    
    def __init__(self, bot, database, notification_system):
        self.bot = bot
        self.database = database
        self.notification_system = notification_system
        self.reminder_task = None
        
    async def initialize_reminder_system(self):
        """Initialize quest reminder system"""
        try:
            async with self.database.pool.acquire() as conn:
                # Quest reminders table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_reminders (
                        id SERIAL PRIMARY KEY,
                        quest_id VARCHAR(50) NOT NULL,
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        last_reminder_sent TIMESTAMP,
                        reminder_count INTEGER DEFAULT 0,
                        next_reminder_at TIMESTAMP,
                        reminder_frequency_hours INTEGER DEFAULT 72,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # User reminder preferences
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_reminder_preferences (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        enabled BOOLEAN DEFAULT TRUE,
                        first_reminder_hours INTEGER DEFAULT 72,
                        second_reminder_hours INTEGER DEFAULT 168,
                        final_reminder_hours INTEGER DEFAULT 336,
                        auto_cancel_after_days INTEGER DEFAULT 21,
                        PRIMARY KEY (user_id, guild_id)
                    )
                ''')
                
            logger.info("✅ Quest reminder system initialized")
            
            # Start reminder processing
            self.reminder_task = asyncio.create_task(self._reminder_loop())
            
        except Exception as e:
            logger.error(f"❌ Error initializing quest reminders: {e}")
    
    async def create_reminder(self, quest_id: str, user_id: int, guild_id: int):
        """Create reminder for newly accepted quest"""
        try:
            prefs = await self._get_user_reminder_preferences(user_id, guild_id)
            first_reminder_time = datetime.now() + timedelta(hours=prefs['first_reminder_hours'])
            
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_reminders (quest_id, user_id, guild_id, next_reminder_at, reminder_frequency_hours)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (quest_id, user_id) DO NOTHING
                ''', quest_id, user_id, guild_id, first_reminder_time, prefs['first_reminder_hours'])
                
        except Exception as e:
            logger.error(f"❌ Error creating quest reminder: {e}")
    
    async def cancel_reminder(self, quest_id: str, user_id: int):
        """Cancel reminder when quest is completed or cancelled"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE quest_reminders 
                    SET is_active = FALSE 
                    WHERE quest_id = $1 AND user_id = $2
                ''', quest_id, user_id)
                
        except Exception as e:
            logger.error(f"❌ Error cancelling quest reminder: {e}")
    
    async def _reminder_loop(self):
        """Main reminder processing loop"""
        while True:
            try:
                await self._process_pending_reminders()
                await asyncio.sleep(3600)  # Check every hour
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in reminder loop: {e}")
                await asyncio.sleep(3600)
    
    async def _process_pending_reminders(self):
        """Process all pending reminders"""
        try:
            current_time = datetime.now()
            
            async with self.database.pool.acquire() as conn:
                # Get due reminders
                reminders = await conn.fetch('''
                    SELECT r.*, q.title, q.description, q.rank, q.category
                    FROM quest_reminders r
                    JOIN quests q ON r.quest_id = q.quest_id
                    WHERE r.is_active = TRUE 
                    AND r.next_reminder_at <= $1
                    AND EXISTS (
                        SELECT 1 FROM quest_progress qp 
                        WHERE qp.quest_id = r.quest_id 
                        AND qp.user_id = r.user_id 
                        AND qp.status = 'accepted'
                    )
                ''', current_time)
                
                for reminder in reminders:
                    await self._send_reminder(reminder)
                    await self._update_reminder_schedule(reminder)
                    
        except Exception as e:
            logger.error(f"❌ Error processing reminders: {e}")
    
    async def _send_reminder(self, reminder: Dict):
        """Send individual quest reminder"""
        try:
            quest_id = reminder['quest_id']
            user_id = reminder['user_id']
            guild_id = reminder['guild_id']
            reminder_count = reminder['reminder_count'] + 1
            
            # Get quest acceptance date for time calculations
            async with self.database.pool.acquire() as conn:
                quest_progress = await conn.fetchrow('''
                    SELECT accepted_at FROM quest_progress 
                    WHERE quest_id = $1 AND user_id = $2
                ''', quest_id, user_id)
            
            if not quest_progress:
                return
                
            days_since_accepted = (datetime.now() - quest_progress['accepted_at']).days
            
            # Create reminder message based on reminder count
            if reminder_count == 1:
                title = "📋 Quest Reminder"
                content = (f"Hey! You accepted the quest **{reminder['title']}** {days_since_accepted} days ago. "
                          f"Don't forget to work on it when you have time!\n\n"
                          f"**Quest Details:**\n"
                          f"• Rank: {reminder['rank'].title()}\n"
                          f"• Category: {reminder['category'].title()}\n"
                          f"• ID: `{quest_id}`\n\n"
                          f"Use `/quest_info {quest_id}` to see full requirements.")
                          
            elif reminder_count == 2:
                title = "⏰ Quest Progress Check"
                content = (f"It's been {days_since_accepted} days since you accepted **{reminder['title']}**. "
                          f"How's it going?\n\n"
                          f"**Need help?**\n"
                          f"• Check requirements: `/quest_info {quest_id}`\n"
                          f"• Ask in quest channels for tips\n"
                          f"• Cancel if you changed your mind: `/cancel_quest {quest_id}`\n\n"
                          f"Remember: Completing quests earns points and helps you rank up!")
                          
            else:  # Final reminder
                title = "⚠️ Final Quest Reminder"
                content = (f"**{reminder['title']}** has been pending for {days_since_accepted} days. "
                          f"This is your final reminder!\n\n"
                          f"**Options:**\n"
                          f"• Complete it: `/submit_quest {quest_id} [proof]`\n"
                          f"• Cancel it: `/cancel_quest {quest_id}`\n"
                          f"• Get help: Ask in quest channels\n\n"
                          f"Uncompleted quests may be auto-cancelled to free up your quest slots.")
            
            # Send notification through enhanced notification system
            await self.notification_system.queue_notification(
                user_id=user_id,
                guild_id=guild_id,
                notification_type='quest_reminder',
                title=title,
                content=content,
                priority='normal'
            )
            
        except Exception as e:
            logger.error(f"❌ Error sending quest reminder: {e}")
    
    async def _update_reminder_schedule(self, reminder: Dict):
        """Update reminder schedule for next reminder"""
        try:
            reminder_count = reminder['reminder_count'] + 1
            prefs = await self._get_user_reminder_preferences(reminder['user_id'], reminder['guild_id'])
            
            # Calculate next reminder time
            if reminder_count == 1:
                next_hours = prefs['second_reminder_hours']
            elif reminder_count == 2:
                next_hours = prefs['final_reminder_hours']
            else:
                # After final reminder, check for auto-cancellation
                auto_cancel_days = prefs['auto_cancel_after_days']
                if auto_cancel_days > 0:
                    await self._schedule_auto_cancel(reminder, auto_cancel_days)
                next_hours = None
            
            async with self.database.pool.acquire() as conn:
                if next_hours:
                    next_reminder_time = datetime.now() + timedelta(hours=next_hours)
                    await conn.execute('''
                        UPDATE quest_reminders 
                        SET reminder_count = $1, 
                            last_reminder_sent = CURRENT_TIMESTAMP,
                            next_reminder_at = $2
                        WHERE id = $3
                    ''', reminder_count, next_reminder_time, reminder['id'])
                else:
                    # No more reminders scheduled
                    await conn.execute('''
                        UPDATE quest_reminders 
                        SET reminder_count = $1, 
                            last_reminder_sent = CURRENT_TIMESTAMP,
                            next_reminder_at = NULL,
                            is_active = FALSE
                        WHERE id = $1
                    ''', reminder_count, reminder['id'])
                    
        except Exception as e:
            logger.error(f"❌ Error updating reminder schedule: {e}")
    
    async def _schedule_auto_cancel(self, reminder: Dict, days: int):
        """Schedule automatic quest cancellation"""
        try:
            # This would integrate with a task scheduler
            # For now, we'll just log that it should be cancelled
            cancel_date = datetime.now() + timedelta(days=days)
            logger.info(f"📅 Quest {reminder['quest_id']} scheduled for auto-cancel at {cancel_date}")
            
        except Exception as e:
            logger.error(f"❌ Error scheduling auto-cancel: {e}")
    
    async def _get_user_reminder_preferences(self, user_id: int, guild_id: int) -> Dict:
        """Get user's reminder preferences"""
        try:
            async with self.database.pool.acquire() as conn:
                prefs = await conn.fetchrow('''
                    SELECT * FROM quest_reminder_preferences 
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)
                
                if prefs:
                    return dict(prefs)
                else:
                    # Return defaults
                    return {
                        'enabled': True,
                        'first_reminder_hours': 72,    # 3 days
                        'second_reminder_hours': 168,  # 7 days  
                        'final_reminder_hours': 336,   # 14 days
                        'auto_cancel_after_days': 21   # 21 days
                    }
                    
        except Exception as e:
            logger.error(f"❌ Error getting reminder preferences: {e}")
            return {
                'enabled': True,
                'first_reminder_hours': 72,
                'second_reminder_hours': 168,
                'final_reminder_hours': 336,
                'auto_cancel_after_days': 21
            }
    
    async def update_user_preferences(self, user_id: int, guild_id: int, **kwargs):
        """Update user's reminder preferences"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get current preferences
                current_prefs = await conn.fetchrow('''
                    SELECT * FROM quest_reminder_preferences 
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)
                
                if current_prefs:
                    # Update existing preferences
                    update_fields = []
                    update_values = []
                    param_count = 3
                    
                    if 'enabled' in kwargs and kwargs['enabled'] is not None:
                        update_fields.append(f'enabled = ${param_count}')
                        update_values.append(kwargs['enabled'])
                        param_count += 1
                    
                    if 'first_reminder_hours' in kwargs and kwargs['first_reminder_hours'] is not None:
                        update_fields.append(f'first_reminder_hours = ${param_count}')
                        update_values.append(kwargs['first_reminder_hours'])
                        param_count += 1
                    
                    if 'final_reminder_hours' in kwargs and kwargs['final_reminder_hours'] is not None:
                        update_fields.append(f'final_reminder_hours = ${param_count}')
                        update_values.append(kwargs['final_reminder_hours'])
                        param_count += 1
                    
                    if update_fields:
                        query = f'''
                            UPDATE quest_reminder_preferences 
                            SET {', '.join(update_fields)}
                            WHERE user_id = $1 AND guild_id = $2
                        '''
                        await conn.execute(query, user_id, guild_id, *update_values)
                else:
                    # Insert new preferences
                    await conn.execute('''
                        INSERT INTO quest_reminder_preferences 
                        (user_id, guild_id, enabled, first_reminder_hours, final_reminder_hours)
                        VALUES ($1, $2, $3, $4, $5)
                    ''', user_id, guild_id,
                        kwargs.get('enabled', True),
                        kwargs.get('first_reminder_hours', 72),
                        kwargs.get('final_reminder_hours', 336)
                    )
                
        except Exception as e:
            logger.error(f"❌ Error updating reminder preferences: {e}")
    
    def stop_reminder_system(self):
        """Stop reminder system"""
        if self.reminder_task and not self.reminder_task.done():
            self.reminder_task.cancel()
        logger.info("🔔 Quest reminder system stopped")