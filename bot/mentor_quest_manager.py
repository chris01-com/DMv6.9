import discord
from discord import app_commands
from discord.ext import commands
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from bot.utils import create_success_embed, create_error_embed, create_info_embed
from bot.sql_database import SQLDatabase

logger = logging.getLogger(__name__)

class MentorQuestManager:
    """Manages mentor-specific quest system with separate database tables"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
        
    async def initialize_mentor_quest_tables(self):
        """Create mentor quest management database tables"""
        try:
            async with self.database.pool.acquire() as conn:
                # Create mentor quests table (separate from regular quests)
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS mentor_quests (
                        quest_id VARCHAR(255) PRIMARY KEY,
                        title VARCHAR(500) NOT NULL,
                        description TEXT NOT NULL,
                        creator_id BIGINT NOT NULL,
                        disciple_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        requirements TEXT DEFAULT '',
                        reward TEXT DEFAULT '',
                        rank VARCHAR(50) DEFAULT 'Starter',
                        category VARCHAR(50) DEFAULT 'Mentorship',
                        status VARCHAR(50) DEFAULT 'available',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        required_role_ids BIGINT[] DEFAULT ARRAY[]::BIGINT[]
                    )
                ''')
                
                # Create mentor quest progress table (separate from regular quest progress)
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS mentor_quest_progress (
                        quest_id VARCHAR(255) NOT NULL,
                        user_id BIGINT NOT NULL,
                        mentor_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        status VARCHAR(50) NOT NULL,
                        accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        submitted_at TIMESTAMP,
                        approved_at TIMESTAMP,
                        proof_text TEXT DEFAULT '',
                        proof_image_urls TEXT[] DEFAULT ARRAY[]::TEXT[],
                        approval_status VARCHAR(50) DEFAULT '',
                        channel_id BIGINT,
                        PRIMARY KEY (quest_id, user_id)
                    )
                ''')
                
                logger.info("✅ Mentor quest tables created successfully")
                
        except Exception as e:
            logger.error(f"❌ Error creating mentor quest tables: {e}")
            
    async def create_mentor_quest(self, quest_id: str, title: str, description: str, 
                                mentor_id: int, student_id: int, guild_id: int,
                                requirements: str = "", reward: str = "", 
                                rank: str = "Starter", category: str = "Mentorship",
                                required_role_ids: List[int] = None) -> bool:
        """Create a new mentor quest"""
        try:
            if required_role_ids is None:
                required_role_ids = []
                
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO mentor_quests 
                    (quest_id, title, description, creator_id, disciple_id, guild_id, 
                     requirements, reward, rank, category, status, required_role_ids)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ''', quest_id, title, description, mentor_id, student_id, guild_id,
                     requirements, reward, rank, category, 'available', required_role_ids)
                
                logger.info(f"✅ Created mentor quest {quest_id} by mentor {mentor_id} for student {student_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error creating mentor quest: {e}")
            return False
    
    async def get_mentor_quest(self, quest_id: str) -> Optional[Dict]:
        """Get mentor quest details"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchrow('''
                    SELECT * FROM mentor_quests WHERE quest_id = $1
                ''', quest_id)
                
                if result:
                    return dict(result)
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting mentor quest {quest_id}: {e}")
            return None
    
    async def get_mentor_quests_for_student(self, student_id: int, guild_id: int) -> List[Dict]:
        """Get all mentor quests for a specific student"""
        try:
            async with self.database.pool.acquire() as conn:
                results = await conn.fetch('''
                    SELECT * FROM mentor_quests 
                    WHERE disciple_id = $1 AND guild_id = $2
                    ORDER BY created_at DESC
                ''', student_id, guild_id)
                
                return [dict(result) for result in results]
                
        except Exception as e:
            logger.error(f"❌ Error getting mentor quests for student {student_id}: {e}")
            return []
    
    async def get_mentor_quests_by_mentor(self, mentor_id: int, guild_id: int) -> List[Dict]:
        """Get all mentor quests created by a specific mentor"""
        try:
            async with self.database.pool.acquire() as conn:
                results = await conn.fetch('''
                    SELECT * FROM mentor_quests 
                    WHERE creator_id = $1 AND guild_id = $2
                    ORDER BY created_at DESC
                ''', mentor_id, guild_id)
                
                return [dict(result) for result in results]
                
        except Exception as e:
            logger.error(f"❌ Error getting mentor quests by mentor {mentor_id}: {e}")
            return []
    
    async def submit_mentor_quest(self, quest_id: str, student_id: int, 
                                proof_text: str, proof_image_urls: List[str] = None,
                                channel_id: int = None) -> bool:
        """Submit a mentor quest for approval"""
        try:
            if proof_image_urls is None:
                proof_image_urls = []
                
            logger.info(f"🔄 Attempting to submit mentor quest {quest_id} for student {student_id}")
                
            async with self.database.pool.acquire() as conn:
                # Check if quest exists and belongs to this student
                quest = await conn.fetchrow('''
                    SELECT quest_id, title, description, creator_id as mentor_id, disciple_id as student_id, guild_id,
                           requirements, reward, rank, category, status, created_at
                    FROM mentor_quests 
                    WHERE quest_id = $1 AND disciple_id = $2
                ''', quest_id, student_id)
                
                if not quest:
                    logger.error(f"❌ Mentor quest {quest_id} not found for student {student_id}")
                    return False
                
                logger.info(f"✅ Found mentor quest: {quest['title']} for student {student_id}")
                
                # Check if already submitted
                existing_progress = await conn.fetchrow('''
                    SELECT status FROM mentor_quest_progress 
                    WHERE quest_id = $1 AND user_id = $2
                ''', quest_id, student_id)
                
                if existing_progress:
                    logger.info(f"🔄 Updating existing progress for quest {quest_id}")
                    # Update existing progress record
                    await conn.execute('''
                        UPDATE mentor_quest_progress 
                        SET status = 'submitted', submitted_at = $1, proof_text = $2, 
                            proof_image_urls = $3, channel_id = $4
                        WHERE quest_id = $5 AND user_id = $6
                    ''', datetime.now(), proof_text, proof_image_urls, channel_id, quest_id, student_id)
                else:
                    logger.info(f"🔄 Creating new progress record for quest {quest_id}")
                    # Insert new progress record - ensure all required fields are present
                    await conn.execute('''
                        INSERT INTO mentor_quest_progress 
                        (quest_id, user_id, guild_id, mentor_id, status, accepted_at, submitted_at,
                         proof_text, proof_image_urls, channel_id)
                        VALUES ($1, $2, $3, $4, 'submitted', $5, $6, $7, $8, $9)
                    ''', quest_id, student_id, quest['guild_id'], quest['mentor_id'],
                         datetime.now(), datetime.now(), proof_text, proof_image_urls, channel_id)
                
                logger.info(f"✅ Student {student_id} submitted mentor quest {quest_id}")
                
                # Notify the mentor about the submission - get bot instance from database
                bot = getattr(self.database, 'bot', None)
                if not bot:
                    # Try to get from main bot if database doesn't have reference
                    try:
                        import main
                        bot = main.bot
                    except:
                        logger.error("❌ Could not get bot instance for notification")
                        return True  # Quest was submitted successfully, just notification failed
                
                await self._notify_mentor_of_submission(quest, student_id, proof_text, bot)
                
                return True
                
        except KeyError as ke:
            logger.error(f"❌ KeyError in submit_mentor_quest: Missing field {ke}")
            logger.error(f"Quest data: {quest if 'quest' in locals() else 'Quest not loaded'}")
            return False
        except Exception as e:
            logger.error(f"❌ Error submitting mentor quest {quest_id}: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    async def approve_mentor_quest(self, quest_id: str, student_id: int, 
                                 mentor_id: int, approved: bool = True,
                                 approval_notes: str = "") -> bool:
        """Approve or reject a mentor quest submission"""
        try:
            status = "approved" if approved else "rejected"
            
            async with self.database.pool.acquire() as conn:
                # Update progress record
                await conn.execute('''
                    UPDATE mentor_quest_progress 
                    SET status = $1, approved_at = $2, approval_status = $3
                    WHERE quest_id = $4 AND user_id = $5 AND mentor_id = $6
                ''', status, datetime.now(), approval_notes, quest_id, student_id, mentor_id)
                
                logger.info(f"✅ Mentor {mentor_id} {status} quest {quest_id} for student {student_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error approving mentor quest: {e}")
            return False
    
    async def get_mentor_quest_progress(self, quest_id: str, student_id: int) -> Optional[Dict]:
        """Get mentor quest progress for a specific student"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchrow('''
                    SELECT * FROM mentor_quest_progress 
                    WHERE quest_id = $1 AND user_id = $2
                ''', quest_id, student_id)
                
                if result:
                    return dict(result)
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting mentor quest progress: {e}")
            return None
    
    async def _notify_mentor_of_submission(self, quest: Dict, student_id: int, proof_text: str, bot=None):
        """Send notification to mentor when student submits a quest"""
        try:
            # Get bot instance
            if not bot:
                logger.error("❌ Bot instance not provided for notification")
                return
            
            guild = bot.get_guild(quest['guild_id'])
            if not guild:
                logger.warning(f"⚠️ Could not find guild {quest['guild_id']} for notification")
                return
            
            # Get mentor and student objects
            mentor = guild.get_member(quest['mentor_id'])
            student = guild.get_member(student_id)
            
            if not mentor:
                logger.warning(f"⚠️ Could not find mentor {quest['mentor_id']} for notification")
                return
            
            if not student:
                logger.warning(f"⚠️ Could not find student {student_id} for notification")
                return
            
            # Get the configured mentor quest channel
            from bot.config import ChannelConfig
            from bot.utils import create_info_embed
            channel_config = ChannelConfig(self.database)
            mentor_quest_channel_id = await channel_config.get_mentor_quest_channel(quest['guild_id'])
            
            logger.info(f"🔍 Looking for mentor quest channel for guild {quest['guild_id']}")
            logger.info(f"🔍 Retrieved mentor quest channel ID: {mentor_quest_channel_id}")
            
            # Create notification using standard embed format
            embed = create_info_embed(
                title="Mentor Quest Submission Received",
                description=f"{mentor.mention} Your student **{student.display_name}** has submitted proof for a quest you assigned!",
                fields=[
                    {
                        "name": "Quest Details",
                        "value": (
                            f"**Quest ID:** `{quest['quest_id']}`\n"
                            f"**Title:** {quest['title']}\n"
                            f"**Student:** {student.mention}\n"
                            f"**Category:** {quest['category']}\n"
                            f"**Rank:** {quest['rank']}\n"
                            f"**Mentor:** {mentor.mention}"
                        ),
                        "inline": False
                    },
                    {
                        "name": "Submitted Proof",
                        "value": f"```{proof_text[:500] + '...' if len(proof_text) > 500 else proof_text}```",
                        "inline": False
                    },
                    {
                        "name": "Next Steps",
                        "value": f"Use `/approve_starter_quest quest_id:{quest['quest_id']} student:{student.mention}` to approve/reject this mentor quest submission.",
                        "inline": False
                    }
                ]
            )
            
            # Send to configured mentor quest channel if available
            if mentor_quest_channel_id:
                channel = guild.get_channel(mentor_quest_channel_id)
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        # Send the ping message with embed
                        await channel.send(content=f"{mentor.mention}", embed=embed)
                        logger.info(f"✅ Sent mentor quest submission notification to {channel.name}")
                        return
                    except discord.Forbidden:
                        logger.warning(f"⚠️ Cannot send message to mentor quest channel {channel.name}")
                else:
                    logger.warning(f"⚠️ Configured mentor quest channel {mentor_quest_channel_id} not found or not a text channel")
            
            # Fallback: Send DM to mentor if no channel configured
            try:
                embed.description = f"Your student **{student.display_name}** has submitted proof for a quest you assigned."
                await mentor.send(embed=embed)
                logger.info(f"✅ Sent submission notification via DM to mentor {mentor.display_name}")
            except discord.Forbidden:
                logger.warning(f"⚠️ Cannot send DM to mentor {mentor.display_name} and no mentor quest channel configured")
                            
        except Exception as e:
            logger.error(f"❌ Error sending mentor notification: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
    
    async def get_pending_mentor_submissions(self, mentor_id: int, guild_id: int) -> List[Dict]:
        """Get all pending mentor quest submissions for a mentor"""
        try:
            async with self.database.pool.acquire() as conn:
                results = await conn.fetch('''
                    SELECT mqp.*, mq.title, mq.description, mq.reward
                    FROM mentor_quest_progress mqp
                    JOIN mentor_quests mq ON mqp.quest_id = mq.quest_id
                    WHERE mqp.mentor_id = $1 AND mqp.guild_id = $2 
                    AND mqp.status = 'submitted'
                    ORDER BY mqp.accepted_at DESC
                ''', mentor_id, guild_id)
                
                return [dict(result) for result in results]
                
        except Exception as e:
            logger.error(f"❌ Error getting pending mentor submissions: {e}")
            return []
    
    async def get_student_mentor_relationship(self, student_id: int, guild_id: int) -> Optional[Dict]:
        """Get mentor-student relationship information"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchrow('''
                    SELECT mentor_id, user_id as student_id, join_date, 
                           quest_1_completed, quest_2_completed, 
                           new_disciple_role_awarded, mentor_channel_id
                    FROM welcome_automation 
                    WHERE user_id = $1 AND guild_id = $2
                ''', student_id, guild_id)
                
                if result:
                    return dict(result)
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting student mentor relationship: {e}")
            return None

    async def remove_starter_quests(self, student_id: int, guild_id: int) -> bool:
        """Remove starter quests from regular quest system when student chooses mentor"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get starter quest IDs for this student
                starter_quest_ids = ['starter1', 'starter2', 'starter3', 'starter4']
                
                # Remove from quest_progress table
                for quest_id in starter_quest_ids:
                    await conn.execute('''
                        DELETE FROM quest_progress 
                        WHERE quest_id = $1 AND user_id = $2 AND guild_id = $3
                    ''', quest_id, student_id, guild_id)
                
                logger.info(f"✅ Removed starter quests for student {student_id} who chose mentor")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error removing starter quests: {e}")
            return False