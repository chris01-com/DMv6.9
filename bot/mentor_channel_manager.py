import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, List, Dict
from bot.utils import create_success_embed, create_error_embed, create_info_embed
from bot.sql_database import SQLDatabase

logger = logging.getLogger(__name__)


class MentorChannelManager:
    """Manages dedicated mentor channels for student-mentor interactions"""

    def __init__(self, database: SQLDatabase):
        self.database = database

    async def create_mentor_channel(
            self, mentor: discord.Member,
            guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Create a dedicated channel for a mentor"""
        try:
            # Create channel name
            channel_name = f"mentor-{mentor.display_name.lower().replace(' ', '-')}"

            # Find or create mentor category
            category = await self._get_or_create_mentor_category(guild)

            # Check if channel already exists
            existing_channel = discord.utils.get(guild.channels,
                                                 name=channel_name)
            if existing_channel:
                logger.info(f"✅ Using existing mentor channel {channel_name}")
                return existing_channel

            # Set up channel permissions with your specified requirements
            overwrites = {
                guild.default_role:
                discord.PermissionOverwrite(read_messages=False),
                mentor:
                discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    embed_links=True,  # send gif, send link
                    attach_files=True,  # send image
                    read_message_history=True,
                    use_application_commands=True,  # application command allowed
                    manage_messages=True
                )
            }

            # Create the channel
            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=
                f"Mentor {mentor.display_name}'s training chamber - Students and mentor only"
            )

            # Update database with channel ID
            await self._update_mentor_channel_id(mentor.id, guild.id,
                                                 channel.id)

            # Send welcome message to channel
            await self._send_channel_welcome_message(channel, mentor)

            logger.info(
                f"✅ Created mentor channel {channel_name} for {mentor.display_name}"
            )
            return channel

        except Exception as e:
            logger.error(
                f"❌ Error creating mentor channel for {mentor.display_name}: {e}"
            )
            return None

    async def add_student_to_mentor_channel(self, student: discord.Member,
                                            mentor: discord.Member) -> bool:
        """Add a student to their mentor's channel"""
        try:
            # Get mentor's channel from database
            mentor_channel_id = await self._get_mentor_channel_id(
                mentor.id, student.guild.id)

            if not mentor_channel_id:
                # Create channel if it doesn't exist
                channel = await self.create_mentor_channel(
                    mentor, student.guild)
                if not channel:
                    logger.error(
                        f"❌ Failed to create mentor channel for {mentor.display_name}"
                    )
                    return False
            else:
                channel = student.guild.get_channel(mentor_channel_id)
                if not channel:
                    # Channel was deleted, recreate it
                    channel = await self.create_mentor_channel(
                        mentor, student.guild)
                    if not channel:
                        logger.error(
                            f"❌ Failed to recreate mentor channel for {mentor.display_name}"
                        )
                        return False

            # Add student permissions to the channel with your specified requirements
            await channel.set_permissions(student,
                                          read_messages=True,
                                          send_messages=True,
                                          embed_links=True,  # send gif, send link
                                          attach_files=True,  # send image
                                          read_message_history=True,
                                          use_application_commands=True  # application command allowed
                                          )

            # Send detailed introduction embed for new student
            embed = self._create_student_introduction_embed(student, mentor)

            embed.add_field(
                name="━━━━━━━━━ Training Guidelines ━━━━━━━━━",
                value=
                (f"▸ **Mentor:** {mentor.mention} will assign personalized quests\n"
                 f"▸ **Student:** {student.mention} will complete and submit quests\n"
                 f"▸ **Communication:** Use this channel for all training discussions\n"
                 f"▸ **Respect:** Maintain sect hierarchy and mutual respect\n"
                 f"▸ **Progress:** Track advancement through quest completions"
                 ),
                inline=False)

            embed.add_field(
                name="━━━━━━━━━ Available Commands ━━━━━━━━━",
                value=(f"**For Mentor ({mentor.mention}):**\n"
                       f"▸ `/give_quest` - Create personalized quests\n"
                       f"▸ `/approve_starter_quest` - Review submissions\n\n"
                       f"**For Student ({student.mention}):**\n"
                       f"▸ `/submit_starter` - Submit quest completions\n"
                       f"▸ Ask questions and seek guidance"),
                inline=False)

            await channel.send(embed=embed)

            # Update student count
            await self._increment_mentor_student_count(mentor.id,
                                                       student.guild.id)

            logger.info(
                f"✅ Added student {student.display_name} to mentor channel for {mentor.display_name}"
            )
            return True

        except Exception as e:
            logger.error(f"❌ Error adding student to mentor channel: {e}")
            return False

    async def remove_student_from_mentor_channel(
            self, student: discord.Member, mentor: discord.Member) -> bool:
        """Remove a student from their mentor's channel"""
        try:
            mentor_channel_id = await self._get_mentor_channel_id(
                mentor.id, student.guild.id)

            if mentor_channel_id:
                channel = student.guild.get_channel(mentor_channel_id)
                if channel:
                    # Remove student permissions
                    await channel.set_permissions(student, overwrite=None)

                    # Send farewell message
                    embed = create_info_embed(
                        "Student Departed",
                        f"**{student.display_name}** has left {mentor.display_name}'s training",
                        "The cultivation path continues in different directions."
                    )

                    await channel.send(embed=embed)

                    # Update student count
                    await self._decrement_mentor_student_count(
                        mentor.id, student.guild.id)

                    logger.info(
                        f"✅ Removed student {student.display_name} from mentor channel for {mentor.display_name}"
                    )
                    return True

            return False

        except Exception as e:
            logger.error(f"❌ Error removing student from mentor channel: {e}")
            return False

    async def get_mentor_channels(
            self, guild: discord.Guild) -> List[discord.TextChannel]:
        """Get all mentor channels in the guild"""
        try:
            async with self.database.pool.acquire() as conn:
                results = await conn.fetch(
                    '''
                    SELECT mentor_channel_id FROM mentors 
                    WHERE guild_id = $1 AND mentor_channel_id IS NOT NULL AND is_active = TRUE
                ''', guild.id)

                channels = []
                for result in results:
                    channel = guild.get_channel(result['mentor_channel_id'])
                    if channel:
                        channels.append(channel)

                return channels

        except Exception as e:
            logger.error(f"❌ Error getting mentor channels: {e}")
            return []

    async def setup_all_mentor_channels(self, guild: discord.Guild) -> int:
        """Set up channels for all registered mentors"""
        try:
            async with self.database.pool.acquire() as conn:
                mentor_records = await conn.fetch(
                    '''
                    SELECT user_id FROM mentors 
                    WHERE guild_id = $1 AND is_active = TRUE
                ''', guild.id)

                created_count = 0
                for record in mentor_records:
                    mentor = guild.get_member(record['user_id'])
                    if mentor:
                        channel = await self.create_mentor_channel(
                            mentor, guild)
                        if channel:
                            created_count += 1

                logger.info(
                    f"✅ Set up {created_count} mentor channels for guild {guild.name}"
                )
                return created_count

        except Exception as e:
            logger.error(f"❌ Error setting up mentor channels: {e}")
            return 0

    async def _get_or_create_mentor_category(
            self, guild: discord.Guild) -> Optional[discord.CategoryChannel]:
        """Get or create the mentor category"""
        try:
            # Look for existing mentor category
            category = discord.utils.get(guild.categories,
                                         name="🏛️ Mentor Training Chambers")

            if not category:
                # Create mentor category
                overwrites = {
                    guild.default_role:
                    discord.PermissionOverwrite(read_messages=False)
                }

                category = await guild.create_category(
                    name="🏛️ Mentor Training Chambers", overwrites=overwrites)

                logger.info(f"✅ Created mentor category in {guild.name}")

            return category

        except Exception as e:
            logger.error(f"❌ Error creating mentor category: {e}")
            return None

    async def _send_channel_welcome_message(self, channel: discord.TextChannel,
                                            mentor: discord.Member):
        """Send welcome message to newly created mentor channel"""
        try:
            embed = create_info_embed(
                f"🏛️ {mentor.display_name}'s Training Chamber",
                "Welcome to your dedicated mentorship space",
                "This channel is exclusively for you and your assigned students."
            )

            embed.add_field(
                name="━━━━━━━━━ Chamber Purpose ━━━━━━━━━",
                value=
                (f"▸ **Mentor:** Guide students through personalized quests\n"
                 f"▸ **Students:** Complete training and seek guidance\n"
                 f"▸ **Communication:** Private space for mentor-student discussions\n"
                 f"▸ **Progress Tracking:** Monitor student advancement\n"
                 f"▸ **Sect Integration:** Bridge to full sect membership"),
                inline=False)

            embed.add_field(
                name="━━━━━━━━━ Getting Started ━━━━━━━━━",
                value=
                (f"▸ Students will be automatically added when they choose you\n"
                 f"▸ Use `/give_quest` to assign personalized training\n"
                 f"▸ Review submissions with `/approve_starter_quest`\n"
                 f"▸ Pin important messages for easy reference\n"
                 f"▸ Maintain the Heavenly Demon Sect's standards"),
                inline=False)

            # Pin the welcome message
            message = await channel.send(embed=embed)
            await message.pin()

        except Exception as e:
            logger.error(f"❌ Error sending channel welcome message: {e}")

    async def _get_mentor_channel_id(self, mentor_id: int,
                                     guild_id: int) -> Optional[int]:
        """Get mentor's channel ID from database"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchval(
                    '''
                    SELECT mentor_channel_id FROM mentors 
                    WHERE user_id = $1 AND guild_id = $2
                ''', mentor_id, guild_id)

                return result

        except Exception as e:
            logger.error(f"❌ Error getting mentor channel ID: {e}")
            return None

    async def _update_mentor_channel_id(self, mentor_id: int, guild_id: int,
                                        channel_id: int):
        """Update mentor's channel ID in database"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute(
                    '''
                    UPDATE mentors 
                    SET mentor_channel_id = $1
                    WHERE user_id = $2 AND guild_id = $3
                ''', channel_id, mentor_id, guild_id)

        except Exception as e:
            logger.error(f"❌ Error updating mentor channel ID: {e}")

    async def _increment_mentor_student_count(self, mentor_id: int,
                                              guild_id: int):
        """Increment mentor's student count"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute(
                    '''
                    UPDATE mentors 
                    SET current_students = current_students + 1
                    WHERE user_id = $1 AND guild_id = $2
                ''', mentor_id, guild_id)

        except Exception as e:
            logger.error(f"❌ Error incrementing mentor student count: {e}")

    async def _decrement_mentor_student_count(self, mentor_id: int,
                                              guild_id: int):
        """Decrement mentor's student count"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute(
                    '''
                    UPDATE mentors 
                    SET current_students = GREATEST(current_students - 1, 0)
                    WHERE user_id = $1 AND guild_id = $2
                ''', mentor_id, guild_id)

        except Exception as e:
            logger.error(f"❌ Error decrementing mentor student count: {e}")

    def _create_student_introduction_embed(
            self, student: discord.Member,
            mentor: discord.Member) -> discord.Embed:
        """Create a comprehensive introduction embed for new student"""
        from datetime import datetime

        # Create standard embed with professional styling
        embed = discord.Embed(
            title="🎓 New Disciple Has Joined!",
            description=
            f"Welcome **{student.display_name}** to {mentor.display_name}'s training chamber",
            color=0x3498DB,  # Standard blue color
            timestamp=datetime.now())

        # Student information section
        embed.add_field(
            name="━━━━━━━━━ Student Information ━━━━━━━━━",
            value=
            (f"**▸ Name:** {student.mention}\n"
             f"**▸ Display Name:** {student.display_name}\n"
             f"**▸ Joined Server:** {student.joined_at.strftime('%B %d, %Y') if student.joined_at else 'Unknown'}\n"
             f"**▸ Account Created:** {student.created_at.strftime('%B %d, %Y')}\n"
             f"**▸ Mentor Assigned:** {mentor.mention}"),
            inline=False)

        # Training guidelines section
        embed.add_field(
            name="━━━━━━━━━ Training Guidelines ━━━━━━━━━",
            value=
            (f"**▸ Mentor:** {mentor.mention} will assign personalized quests\n"
             f"**▸ Student:** {student.mention} will complete and submit quests\n"
             f"**▸ Communication:** Use this channel for all training discussions\n"
             f"**▸ Respect:** Maintain sect hierarchy and mutual respect\n"
             f"**▸ Progress:** Track advancement through quest completions"),
            inline=False)

        # Available commands section
        embed.add_field(
            name="━━━━━━━━━ Available Commands ━━━━━━━━━",
            value=(f"**For Mentor ({mentor.mention}):**\n"
                   f"▸ `/give_quest` - Create personalized quests\n"
                   f"▸ `/approve_starter_quest` - Review submissions\n\n"
                   f"**For Student ({student.mention}):**\n"
                   f"▸ `/submit_starter` - Submit quest completions\n"
                   f"▸ Ask questions and seek guidance anytime"),
            inline=False)

        # Channel permissions information
        embed.add_field(name="━━━━━━━━━ Channel Rules ━━━━━━━━━",
                        value=(f"🔒 **Nothing XD **"),
                        inline=False)

        # Set footer
        embed.set_footer(
            text="Begin your cultivation journey • Heavenly Demon Sect",
            icon_url=student.avatar.url if student.avatar else None)

        return embed
