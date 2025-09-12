import discord
from discord import app_commands
from discord.ext import commands
import logging
import uuid
from datetime import datetime
from typing import Optional, List
from bot.utils import create_success_embed, create_error_embed, create_info_embed
# from bot.permissions import has_mentor_permissions, get_user_permissions
from bot.mentor_quest_manager import MentorQuestManager

logger = logging.getLogger(__name__)

class MentorCommands(commands.Cog):
    """Mentor-specific slash commands for quest management"""

    def __init__(self, bot, database: object, mentor_quest_manager: MentorQuestManager):
        self.bot = bot
        self.database = database
        self.mentor_quest_manager = mentor_quest_manager

    async def is_mentor(self, user_id: int, guild_id: int) -> bool:
        """Check if user is a registered mentor"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchval('''
                    SELECT COUNT(*) FROM mentors 
                    WHERE user_id = $1 AND guild_id = $2 AND is_active = TRUE
                ''', user_id, guild_id)
                return result > 0
        except Exception as e:
            logger.error(f"❌ Error checking mentor status: {e}")
            return False

    async def get_mentor_students(self, mentor_id: int, guild_id: int) -> List[dict]:
        """Get all students assigned to this mentor"""
        try:
            async with self.database.pool.acquire() as conn:
                results = await conn.fetch('''
                    SELECT user_id, join_date, quest_1_completed, quest_2_completed,
                           new_disciple_role_awarded
                    FROM welcome_automation 
                    WHERE mentor_id = $1 AND guild_id = $2
                    ORDER BY join_date DESC
                ''', mentor_id, guild_id)
                return [dict(result) for result in results]
        except Exception as e:
            logger.error(f"❌ Error getting mentor students: {e}")
            return []

    @app_commands.command(name="add_game", description="Add a new cultivation game option for mentor selection (Admin only)")
    @app_commands.describe(
        game_key="Unique identifier for the game (lowercase, no spaces)",
        game_name="Display name for the game",
        emoji="Emoji to represent the game"
    )
    async def add_game(
        self,
        interaction: discord.Interaction,
        game_key: str,
        game_name: str,
        emoji: str
    ):
        """Add a new game option for mentor selection"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
                return

            # Validate input
            if len(game_key) > 50 or len(game_name) > 100 or len(emoji) > 10:
                await interaction.response.send_message("❌ Input too long. Keep game_key under 50 chars, game_name under 100 chars, and emoji under 10 chars.", ephemeral=True)
                return

            if game_key == "none":
                await interaction.response.send_message("❌ Cannot use 'none' as a game key - it's reserved.", ephemeral=True)
                return

            # Create table if it doesn't exist
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS mentor_games (
                        guild_id BIGINT NOT NULL,
                        game_key VARCHAR(50) NOT NULL,
                        game_name VARCHAR(100) NOT NULL,
                        emoji VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (guild_id, game_key)
                    )
                ''')

                # Check if game already exists
                existing = await conn.fetchval('''
                    SELECT COUNT(*) FROM mentor_games 
                    WHERE guild_id = $1 AND game_key = $2
                ''', interaction.guild.id, game_key)

                if existing > 0:
                    await interaction.response.send_message(f"❌ Game '{game_key}' already exists.", ephemeral=True)
                    return

                # Add new game
                await conn.execute('''
                    INSERT INTO mentor_games (guild_id, game_key, game_name, emoji)
                    VALUES ($1, $2, $3, $4)
                ''', interaction.guild.id, game_key, game_name, emoji)

            embed = create_success_embed(
                "New Cultivation Path Added!",
                f"Successfully added new game option:",
                f"**{emoji} {game_name}** (Key: `{game_key}`)\n\nThis will be available in the mentor selection dropdown for new members."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ Added new game: {game_key} - {game_name} to guild {interaction.guild.id}")

        except Exception as e:
            logger.error(f"❌ Error adding game: {e}")
            await interaction.response.send_message("❌ An error occurred while adding the game.", ephemeral=True)

    @app_commands.command(name="remove_game", description="Remove a cultivation game option from mentor selection (Admin only)")
    @app_commands.describe(game_key="The game key to remove")
    async def remove_game(
        self,
        interaction: discord.Interaction,
        game_key: str
    ):
        """Remove a game option from mentor selection"""
        try:
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ You need administrator permissions to use this command.", ephemeral=True)
                return

            if game_key == "none":
                await interaction.response.send_message("❌ Cannot remove the 'none' option - it's required for solo cultivation.", ephemeral=True)
                return

            # Check if game exists and remove it
            async with self.database.pool.acquire() as conn:
                # Get game info before deletion
                game_info = await conn.fetchrow('''
                    SELECT game_name, emoji FROM mentor_games 
                    WHERE guild_id = $1 AND game_key = $2
                ''', interaction.guild.id, game_key)

                if not game_info:
                    await interaction.response.send_message(f"❌ Game '{game_key}' not found.", ephemeral=True)
                    return

                # Remove the game
                await conn.execute('''
                    DELETE FROM mentor_games 
                    WHERE guild_id = $1 AND game_key = $2
                ''', interaction.guild.id, game_key)

            embed = create_success_embed(
                "Cultivation Path Removed!",
                f"Successfully removed game option:",
                f"**{game_info['emoji']} {game_info['game_name']}** (Key: `{game_key}`)\n\nThis option will no longer appear in the mentor selection dropdown."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ Removed game: {game_key} - {game_info['game_name']} from guild {interaction.guild.id}")

        except Exception as e:
            logger.error(f"❌ Error removing game: {e}")
            await interaction.response.send_message("❌ An error occurred while removing the game.", ephemeral=True)

    @app_commands.command(name="give_quest", description="Create a personalized quest for your student (Mentors only)")
    @app_commands.describe(
        student="The student to assign this quest to",
        title="Quest title (max 100 characters)",
        description="Detailed quest description",
        requirements="What the student needs to do",
        reward="Points and rewards for completion",
        rank="Quest difficulty level",
        category="Quest category and focus area"
    )
    @app_commands.choices(rank=[
        app_commands.Choice(name="Easy", value="Easy"),
        app_commands.Choice(name="Normal", value="Normal"),
        app_commands.Choice(name="Hard", value="Hard"),
        app_commands.Choice(name="Impossible", value="Impossible")
    ])
    @app_commands.choices(category=[
        app_commands.Choice(name="Gaming & Combat", value="Gaming"),
        app_commands.Choice(name="Social Engagement", value="Social"),
        app_commands.Choice(name="Skill Development", value="Skill"),
        app_commands.Choice(name="Sect Contribution", value="Contribution"),
        app_commands.Choice(name="Learning & Growth", value="Learning"),
        app_commands.Choice(name="Achievement & Goals", value="Achievement"),
        app_commands.Choice(name="Creative Expression", value="Creative"),
        app_commands.Choice(name="Special Challenge", value="Challenge")
    ])
    async def give_quest(
        self,
        interaction: discord.Interaction,
        student: discord.Member,
        title: str,
        description: str,
        requirements: str = "",
        reward: str = "",
        rank: str = "Easy",
        category: str = "Gaming"
    ):
        """Create a personalized quest for a student"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can create student quests",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if student is assigned to this mentor
            async with self.database.pool.acquire() as conn:
                mentor_relationship = await conn.fetchrow('''
                    SELECT mentor_id FROM welcome_automation 
                    WHERE user_id = $1 AND guild_id = $2
                ''', student.id, interaction.guild.id)

                if not mentor_relationship or mentor_relationship['mentor_id'] != interaction.user.id:
                    embed = create_error_embed(
                        "Invalid Student Assignment",
                        f"{student.display_name} is not your assigned student",
                        "You can only create quests for students assigned to you."
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            # Generate unique quest ID
            quest_id = f"mentor_{uuid.uuid4().hex[:8]}"

            # Validate inputs
            if len(title) > 100:
                title = title[:100]

            # Create the mentor quest
            success = await self.mentor_quest_manager.create_mentor_quest(
                quest_id=quest_id,
                title=title,
                description=description,
                mentor_id=interaction.user.id,
                student_id=student.id,
                guild_id=interaction.guild.id,
                requirements=requirements,
                reward=reward,
                rank=rank,
                category=category
            )

            if not success:
                embed = create_error_embed(
                    "Quest Creation Failed",
                    "Failed to create the mentor quest",
                    "Please try again or contact an administrator."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create success embed
            embed = create_success_embed(
                "Mentor Quest Created Successfully!",
                f"Quest assigned to **{student.display_name}**",
                "Your student has been notified and can now work on this quest."
            )

            embed.add_field(
                name="━━━━━━━━━ Quest Details ━━━━━━━━━",
                value=(
                    f"**▸ Quest ID:** `{quest_id}`\n"
                    f"**▸ Title:** {title}\n"
                    f"**▸ Student:** {student.mention}\n"
                    f"**▸ Rank:** {rank}\n"
                    f"**▸ Category:** {category}\n"
                    f"**▸ Reward:** {reward or 'Not specified'}"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Description ━━━━━━━━━",
                value=description[:1024],  # Discord field limit
                inline=False
            )

            if requirements:
                embed.add_field(
                    name="━━━━━━━━━ Requirements ━━━━━━━━━",
                    value=requirements[:1024],
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

            # Notify student via DM
            await self._notify_student_of_new_quest(student, interaction.user, quest_id, title, description, requirements, reward)

            logger.info(f"✅ Mentor {interaction.user.display_name} created quest {quest_id} for student {student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in give_quest command: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while creating the quest",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="submit_starter", description="Submit proof for a mentor quest (Students only)")
    @app_commands.describe(
        quest_id="The mentor quest ID to submit",
        proof="Proof of quest completion (text)",
        proof_image="Optional image proof"
    )
    async def submit_starter(
        self,
        interaction: discord.Interaction,
        quest_id: str,
        proof: str,
        proof_image: Optional[discord.Attachment] = None
    ):
        """Submit proof for a mentor quest"""
        try:
            # Get the mentor quest
            quest = await self.mentor_quest_manager.get_mentor_quest(quest_id)
            if not quest:
                embed = create_error_embed(
                    "Quest Not Found",
                    f"Mentor quest `{quest_id}` does not exist",
                    "Please check the quest ID and try again."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if this quest belongs to the user
            quest_student_id = quest.get('disciple_id')
            if not quest_student_id or quest_student_id != interaction.user.id:
                embed = create_error_embed(
                    "Access Denied",
                    "This quest is not assigned to you",
                    "You can only submit quests assigned to you by your mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Handle image proof
            proof_image_urls = []
            if proof_image:
                if proof_image.content_type and proof_image.content_type.startswith('image/'):
                    proof_image_urls.append(proof_image.url)
                else:
                    embed = create_error_embed(
                        "Invalid File Type",
                        "Only image files are accepted as proof",
                        "Please attach a valid image file."
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            # Submit the quest
            success = await self.mentor_quest_manager.submit_mentor_quest(
                quest_id=quest_id,
                student_id=interaction.user.id,
                proof_text=proof,
                proof_image_urls=proof_image_urls,
                channel_id=interaction.channel.id
            )

            if not success:
                embed = create_error_embed(
                    "Submission Failed",
                    "Failed to submit the mentor quest",
                    "Please try again or contact your mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create success embed
            embed = create_success_embed(
                "Mentor Quest Submitted!",
                f"Quest `{quest_id}` submitted for approval",
                "Your mentor has been notified and will review your submission."
            )

            embed.add_field(
                name="━━━━━━━━━ Submission Details ━━━━━━━━━",
                value=(
                    f"**▸ Quest:** {quest.get('title', 'Unknown Quest')}\n"
                    f"**▸ Quest ID:** `{quest.get('quest_id', 'Unknown')}`\n"
                    f"**▸ Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"**▸ Proof Images:** {len(proof_image_urls)} attached\n"
                    f"**▸ Status:** Awaiting mentor approval"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Your Proof ━━━━━━━━━",
                value=proof[:1024],
                inline=False
            )

            if proof_image_urls:
                embed.set_image(url=proof_image_urls[0])

            await interaction.response.send_message(embed=embed)

            # Notify mentor
            mentor_id = quest.get('mentor_id')
            if mentor_id:
                mentor = interaction.guild.get_member(mentor_id)
                if mentor:
                    await self._notify_mentor_of_submission(mentor, interaction.user, quest, proof, proof_image_urls)

            logger.info(f"✅ Student {interaction.user.display_name} submitted mentor quest {quest_id}")

        except Exception as e:
            logger.error(f"❌ Error in submit_starter command: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while submitting the quest",
                "Please try again or contact your mentor."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="approve_starter_quest", description="Approve or reject student quest submissions (Mentors only)")
    @app_commands.describe(
        quest_id="The mentor quest ID to approve/reject",
        student="The student who submitted the quest",
        approved="Whether to approve (True) or reject (False) the submission",
        notes="Optional approval/rejection notes",
        points="Custom points to award (only when approved, overrides quest reward)"
    )
    async def approve_starter_quest(
        self,
        interaction: discord.Interaction,
        quest_id: str,
        student: discord.Member,
        approved: bool,
        notes: str = "",
        points: int = None
    ):
        """Approve or reject a student's mentor quest submission"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can approve quest submissions",
                    "Contact an administrator if you believe this is an error."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get the mentor quest
            quest = await self.mentor_quest_manager.get_mentor_quest(quest_id)
            if not quest:
                embed = create_error_embed(
                    "Quest Not Found",
                    f"Mentor quest `{quest_id}` does not exist",
                    "Please check the quest ID and try again."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if this is the mentor's quest
            quest_mentor_id = quest.get('creator_id')
            if not quest_mentor_id or quest_mentor_id != interaction.user.id:
                embed = create_error_embed(
                    "Access Denied",
                    "You can only approve quests you created",
                    "This quest belongs to another mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if quest is for the specified student
            quest_student_id = quest.get('disciple_id')
            if not quest_student_id or quest_student_id != student.id:
                embed = create_error_embed(
                    "Invalid Student",
                    f"Quest `{quest_id}` is not assigned to {student.display_name}",
                    "Please verify the correct student and quest ID."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Approve or reject the quest
            success = await self.mentor_quest_manager.approve_mentor_quest(
                quest_id=quest_id,
                student_id=student.id,
                mentor_id=interaction.user.id,
                approved=approved,
                approval_notes=notes
            )

            if not success:
                embed = create_error_embed(
                    "Approval Failed",
                    "Failed to process the quest approval",
                    "Please try again or contact an administrator."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create success embed
            status = "Approved" if approved else "Rejected"
            embed_func = create_success_embed if approved else create_error_embed

            embed = embed_func(
                f"Quest {status}!",
                f"Quest `{quest_id}` has been {status.lower()}",
                f"Student {student.display_name} has been notified of your decision."
            )

            # Build approval details with custom points info
            approval_details = (
                f"**▸ Quest:** {quest.get('title', 'Unknown Quest')}\n"
                f"**▸ Student:** {student.mention}\n"
                f"**▸ Decision:** {status}\n"
                f"**▸ Reviewed:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"**▸ Mentor:** {interaction.user.mention}"
            )

            if approved and points is not None:
                approval_details += f"\n**▸ Custom Points:** {points}"
            elif approved and quest.get('reward'):
                approval_details += f"\n**▸ Quest Reward:** {quest.get('reward', 'Not specified')}"

            embed.add_field(
                name="━━━━━━━━━ Approval Details ━━━━━━━━━",
                value=approval_details,
                inline=False
            )

            if notes:
                embed.add_field(
                    name="━━━━━━━━━ Review Notes ━━━━━━━━━",
                    value=notes[:1024],
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

            # Notify student of approval/rejection
            await self._notify_student_of_approval(student, interaction.user, quest, approved, notes)

            # If approved, award points (use custom points if provided, otherwise use quest reward)
            if approved:
                if points is not None:
                    # Use custom points parameter
                    await self._award_custom_mentor_quest_points(student, quest, interaction.guild.id, points)
                elif quest.get('reward'):
                    # Use default quest reward points
                    await self._award_mentor_quest_points(student, quest, interaction.guild.id)

            logger.info(f"✅ Mentor {interaction.user.display_name} {status.lower()} quest {quest_id} for {student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in approve_starter_quest command: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while processing the approval",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _notify_student_of_new_quest(self, student: discord.Member, mentor: discord.Member, 
                                         quest_id: str, title: str, description: str, 
                                         requirements: str, reward: str):
        """Notify student of new quest assignment"""
        try:
            embed = create_info_embed(
                "New Quest from Your Mentor!",
                f"**{mentor.display_name}** has assigned you a new quest",
                f"Use `/submit_starter quest_id:{quest_id}` to submit your completion proof."
            )

            embed.add_field(
                name="━━━━━━━━━ Quest Information ━━━━━━━━━",
                value=(
                    f"**▸ Title:** {title}\n"
                    f"**▸ Quest ID:** `{quest_id}`\n"
                    f"**▸ Mentor:** {mentor.mention}\n"
                    f"**▸ Reward:** {reward or 'Ask your mentor'}"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Description ━━━━━━━━━",
                value=description[:1024],
                inline=False
            )

            if requirements:
                embed.add_field(
                    name="━━━━━━━━━ Requirements ━━━━━━━━━",
                    value=requirements[:1024],
                    inline=False
                )

            await student.send(embed=embed)
            logger.info(f"✅ Notified student {student.display_name} of new quest {quest_id}")

        except discord.Forbidden:
            logger.warning(f"⚠️ Could not DM student {student.display_name} - DMs disabled")
        except Exception as e:
            logger.error(f"❌ Error notifying student of new quest: {e}")

    async def _notify_mentor_of_submission(self, mentor: discord.Member, student: discord.Member,
                                         quest: dict, proof: str, proof_image_urls: List[str]):
        """Notify mentor of quest submission"""
        try:
            embed = create_info_embed(
                "Quest Submission Received!",
                f"**{student.display_name}** has submitted a quest for your review",
                f"Use `/approve_starter_quest quest_id:{quest.get('quest_id', 'Unknown')} student:{student.display_name}` to approve or reject."
            )

            embed.add_field(
                name="━━━━━━━━━ Submission Details ━━━━━━━━━",
                value=(
                    f"**▸ Quest:** {quest.get('title', 'Unknown Quest')}\n"
                    f"**▸ Quest ID:** `{quest.get('quest_id', 'Unknown')}`\n"
                    f"**▸ Student:** {student.mention}\n"
                    f"**▸ Submitted:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"**▸ Images:** {len(proof_image_urls)} attached"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Student's Proof ━━━━━━━━━",
                value=proof[:1024],
                inline=False
            )

            if proof_image_urls:
                embed.set_image(url=proof_image_urls[0])

            await mentor.send(embed=embed)
            logger.info(f"✅ Notified mentor {mentor.display_name} of submission from {student.display_name}")

        except discord.Forbidden:
            logger.warning(f"⚠️ Could not DM mentor {mentor.display_name} - DMs disabled")
        except Exception as e:
            logger.error(f"❌ Error notifying mentor of submission: {e}")

    async def _notify_student_of_approval(self, student: discord.Member, mentor: discord.Member,
                                        quest: dict, approved: bool, notes: str):
        """Notify student of quest approval/rejection"""
        try:
            status = "Approved" if approved else "Rejected"
            embed_func = create_success_embed if approved else create_error_embed

            embed = embed_func(
                f"Quest {status}!",
                f"Your mentor has {status.lower()} your quest submission",
                f"Quest: {quest.get('title', 'Unknown Quest')}"
            )

            embed.add_field(
                name="━━━━━━━━━ Review Details ━━━━━━━━━",
                value=(
                    f"**▸ Quest:** {quest.get('title', 'Unknown Quest')}\n"
                    f"**▸ Quest ID:** `{quest.get('quest_id', 'Unknown')}`\n"
                    f"**▸ Mentor:** {mentor.mention}\n"
                    f"**▸ Decision:** {status}\n"
                    f"**▸ Reviewed:** {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
                inline=False
            )

            if notes:
                embed.add_field(
                    name="━━━━━━━━━ Mentor's Notes ━━━━━━━━━",
                    value=notes[:1024],
                    inline=False
                )

            if approved:
                embed.add_field(
                    name="━━━━━━━━━ Congratulations! ━━━━━━━━━",
                    value="You have successfully completed this mentor quest. Continue training with your mentor to advance in the sect!",
                    inline=False
                )
            else:
                embed.add_field(
                    name="━━━━━━━━━ Next Steps ━━━━━━━━━",
                    value="Review your mentor's feedback and try again. You can resubmit once you've addressed their concerns.",
                    inline=False
                )

            await student.send(embed=embed)
            logger.info(f"✅ Notified student {student.display_name} of {status.lower()} for quest {quest.get('quest_id', 'Unknown')}")

        except discord.Forbidden:
            logger.warning(f"⚠️ Could not DM student {student.display_name} - DMs disabled")
        except Exception as e:
            logger.error(f"❌ Error notifying student of approval: {e}")

    async def _award_mentor_quest_points(self, student: discord.Member, quest: dict, guild_id: int):
        """Award points for completed mentor quest"""
        try:
            import re

            # Extract points from reward text
            reward_text = quest.get('reward', '')
            if not reward_text:
                return

            # Look for point values in various formats
            point_patterns = [
                r'(\d+)\s*(?:points?|pts?)',
                r'(\d+)\s*(?:exp?|experience)',
                r'(\d+)\s*(?:contribution|contrib)',
                r'^(\d+)$'  # Just a number
            ]

            points_awarded = 0
            for pattern in point_patterns:
                match = re.search(pattern, reward_text.lower())
                if match:
                    points_awarded = int(match.group(1))
                    break

            if points_awarded > 0:
                # Get leaderboard manager from bot
                bot = self.bot
                if hasattr(bot, 'leaderboard_manager'):
                    success = await bot.leaderboard_manager.add_points(
                        guild_id, student.id, points_awarded, student.display_name
                    )

                    if success:
                        logger.info(f"✅ Awarded {points_awarded} points to {student.display_name} for mentor quest completion")

                        # Trigger leaderboard updates
                        if hasattr(bot, 'role_reward_manager'):
                            await bot.role_reward_manager.trigger_leaderboard_updates(guild_id)
                    else:
                        logger.error(f"❌ Failed to award points to {student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error awarding mentor quest points: {e}")

    async def _award_custom_mentor_quest_points(self, student: discord.Member, quest: dict, guild_id: int, points: int):
        """Award custom points for completed mentor quest"""
        try:
            if points > 0:
                # Get leaderboard manager from bot
                bot = self.bot
                if hasattr(bot, 'leaderboard_manager'):
                    success = await bot.leaderboard_manager.add_points(
                        guild_id, student.id, points, student.display_name
                    )

                    if success:
                        logger.info(f"✅ Awarded {points} custom points to {student.display_name} for mentor quest completion")

                        # Trigger leaderboard updates
                        if hasattr(bot, 'role_reward_manager'):
                            await bot.role_reward_manager.trigger_leaderboard_updates(guild_id)
                    else:
                        logger.error(f"❌ Failed to award custom points to {student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error awarding custom mentor quest points: {e}")

    @app_commands.command(name="mentor_dashboard", description="Comprehensive mentor dashboard with student overview and statistics")
    async def mentor_dashboard(self, interaction: discord.Interaction):
        """Display comprehensive mentor dashboard"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied", 
                    "Only registered mentors can access the mentor dashboard",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Get mentor's students
            students = await self.get_mentor_students(interaction.user.id, interaction.guild.id)

            # Get pending quest submissions
            pending_submissions = await self.mentor_quest_manager.get_pending_mentor_submissions(
                interaction.user.id, interaction.guild.id
            )

            # Get mentor's created quests
            mentor_quests = await self.mentor_quest_manager.get_mentor_quests_by_mentor(
                interaction.user.id, interaction.guild.id
            )

            # Create dashboard embed
            embed = create_info_embed(
                f"🎓 {interaction.user.display_name}'s Mentor Dashboard",
                "Your comprehensive mentoring overview",
                "Track your students' progress and manage your mentoring activities"
            )

            # Student Overview
            if students:
                active_students = len([s for s in students if s.get('quest_1_completed') or s.get('quest_2_completed')])
                total_students = len(students)

                student_overview = f"**▸ Total Students:** {total_students}\n"
                student_overview += f"**▸ Active Students:** {active_students}\n"
                student_overview += f"**▸ Completion Rate:** {(active_students/total_students*100):.1f}%\n"

                # Recent students (last 5)
                recent_students = students[:5]
                student_list = ""
                for student in recent_students:
                    member = interaction.guild.get_member(student['user_id'])
                    if member:
                        progress_emoji = "✅" if student.get('new_disciple_role_awarded') else "🔄"
                        student_list += f"{progress_emoji} {member.display_name}\n"

                embed.add_field(
                    name="━━━━━━━━━ Student Overview ━━━━━━━━━",
                    value=student_overview,
                    inline=True
                )

                if student_list:
                    embed.add_field(
                        name="━━━━━━━━━ Recent Students ━━━━━━━━━",
                        value=student_list[:1024],
                        inline=True
                    )
            else:
                embed.add_field(
                    name="━━━━━━━━━ Student Overview ━━━━━━━━━",
                    value="**▸ No students assigned yet**\n\nNew members will be automatically assigned to you when they join.",
                    inline=False
                )

            # Quest Activity
            quest_summary = f"**▸ Total Quests Created:** {len(mentor_quests)}\n"
            quest_summary += f"**▸ Pending Submissions:** {len(pending_submissions)}\n"

            if mentor_quests:
                completed_quests = len([q for q in mentor_quests if q.get('status') == 'completed'])
                quest_summary += f"**▸ Completed Quests:** {completed_quests}\n"
                quest_summary += f"**▸ Success Rate:** {(completed_quests/len(mentor_quests)*100):.1f}%"

            embed.add_field(
                name="━━━━━━━━━ Quest Activity ━━━━━━━━━",
                value=quest_summary,
                inline=False
            )

            # Pending Actions
            if pending_submissions:
                pending_list = ""
                for submission in pending_submissions[:3]:  # Show first 3
                    student = interaction.guild.get_member(submission['user_id'])
                    if student:
                        pending_list += f"🔔 **{submission['title']}** by {student.display_name}\n"

                if len(pending_submissions) > 3:
                    pending_list += f"... and {len(pending_submissions) - 3} more"

                embed.add_field(
                    name="━━━━━━━━━ Pending Reviews ━━━━━━━━━",
                    value=pending_list,
                    inline=False
                )

            # Quick Actions
            quick_actions = (
                "📋 `/give_quest` - Create new quest for student\n"
                "✅ `/approve_starter_quest` - Review submissions\n"
                "📊 `/quest_templates` - Use quest templates\n"
                "💬 `/mentor_broadcast` - Message all students\n"
                "🤝 `/mentor_council` - Connect with other mentors"
            )

            embed.add_field(
                name="━━━━━━━━━ Quick Actions ━━━━━━━━━",
                value=quick_actions,
                inline=False
            )

            await interaction.followup.send(embed=embed)
            logger.info(f"✅ {interaction.user.display_name} viewed mentor dashboard")

        except Exception as e:
            logger.error(f"❌ Error in mentor_dashboard command: {e}")
            embed = create_error_embed(
                "Dashboard Error",
                "Failed to load mentor dashboard",
                "Please try again or contact support."
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="quest_templates", description="Browse and use pre-made quest templates for faster quest creation")
    async def quest_templates(self, interaction: discord.Interaction):
        """Display available quest templates"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can access quest templates",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create quest templates embed
            embed = create_info_embed(
                "📚 Quest Templates Library",
                "Pre-made quest templates for efficient mentoring",
                "Select a template to use for your students"
            )

            # Template categories
            templates = {
                "🎮 Gaming Mastery": [
                    "Reach level 50 in Shindo Life",
                    "Complete 3 PvP battles in any Roblox game",
                    "Master a new fighting combo",
                    "Join a group training session"
                ],
                "🤝 Social Engagement": [
                    "Help 3 new members in chat",
                    "Participate in server events",
                    "Share cultivation tips with others",
                    "Create a helpful guide or tutorial"
                ],
                "🎯 Skill Development": [
                    "Practice daily meditation (5 days)",
                    "Learn about cultivation lore",
                    "Improve communication skills",
                    "Set and achieve personal goals"
                ],
                "💪 Sect Contribution": [
                    "Recruit 2 new members to the sect",
                    "Organize a group activity",
                    "Create server artwork or memes",
                    "Contribute to sect discussions"
                ]
            }

            for category, template_list in templates.items():
                template_text = "\n".join([f"• {template}" for template in template_list])
                embed.add_field(
                    name=f"━━━━━━━━━ {category} ━━━━━━━━━",
                    value=template_text,
                    inline=False
                )

            # Usage instructions
            usage_info = (
                "**How to use templates:**\n"
                "1. Choose a template from above\n"
                "2. Use `/give_quest` command\n"
                "3. Customize the template for your student\n"
                "4. Add specific requirements and rewards\n"
                "\n**Pro Tip:** Combine multiple templates for complex quests!"
            )

            embed.add_field(
                name="━━━━━━━━━ Template Usage ━━━━━━━━━",
                value=usage_info,
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ {interaction.user.display_name} viewed quest templates")

        except Exception as e:
            logger.error(f"❌ Error in quest_templates command: {e}")
            embed = create_error_embed(
                "Template Error",
                "Failed to load quest templates",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mentor_broadcast", description="Send a message to all your assigned students")
    @app_commands.describe(message="The message to send to all your students")
    async def mentor_broadcast(self, interaction: discord.Interaction, message: str):
        """Broadcast a message to all assigned students"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can broadcast messages",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Get mentor's students
            students = await self.get_mentor_students(interaction.user.id, interaction.guild.id)

            if not students:
                embed = create_info_embed(
                    "No Students Found",
                    "You don't have any assigned students yet",
                    "New members will be automatically assigned to you when they join."
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # Create broadcast embed for students
            broadcast_embed = create_info_embed(
                f"📢 Message from Your Mentor",
                f"**{interaction.user.display_name}** has sent you a message:",
                message
            )

            # Send to all students
            successful_sends = 0
            failed_sends = 0

            for student_data in students:
                student = interaction.guild.get_member(student_data['user_id'])
                if student:
                    try:
                        await student.send(embed=broadcast_embed)
                        successful_sends += 1
                    except discord.Forbidden:
                        failed_sends += 1
                        logger.warning(f"⚠️ Could not DM student {student.display_name} - DMs disabled")
                    except Exception as e:
                        failed_sends += 1
                        logger.error(f"❌ Error sending broadcast to {student.display_name}: {e}")

            # Send confirmation to mentor
            result_embed = create_success_embed(
                "Broadcast Sent!",
                f"Your message has been delivered to your students",
                f"**✅ Successful:** {successful_sends} students\n**❌ Failed:** {failed_sends} students"
            )

            result_embed.add_field(
                name="━━━━━━━━━ Your Message ━━━━━━━━━",
                value=message[:1024],
                inline=False
            )

            await interaction.followup.send(embed=result_embed)
            logger.info(f"✅ {interaction.user.display_name} broadcasted message to {successful_sends} students")

        except Exception as e:
            logger.error(f"❌ Error in mentor_broadcast command: {e}")
            embed = create_error_embed(
                "Broadcast Error",
                "Failed to send broadcast message",
                "Please try again or contact support."
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="student_progress", description="View detailed progress tracking for a specific student")
    @app_commands.describe(student="The student to view progress for")
    async def student_progress(self, interaction: discord.Interaction, student: discord.Member):
        """View detailed student progress tracking"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can view student progress",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            await interaction.response.defer()

            # Check if student is assigned to this mentor
            async with self.database.pool.acquire() as conn:
                mentor_relationship = await conn.fetchrow('''
                    SELECT mentor_id, join_date, quest_1_completed, quest_2_completed, 
                           new_disciple_role_awarded FROM welcome_automation 
                    WHERE user_id = $1 AND guild_id = $2
                ''', student.id, interaction.guild.id)

                if not mentor_relationship or mentor_relationship['mentor_id'] != interaction.user.id:
                    embed = create_error_embed(
                        "Invalid Student Assignment",
                        f"{student.display_name} is not your assigned student",
                        "You can only view progress for students assigned to you."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return

            # Get student's mentor quests and their progress
            async with self.database.pool.acquire() as conn:
                student_quests = await conn.fetch('''
                    SELECT mq.*, mqp.status, mqp.submitted_at, mqp.approved_at
                    FROM mentor_quests mq
                    LEFT JOIN mentor_quest_progress mqp ON mq.quest_id = mqp.quest_id AND mqp.user_id = mq.disciple_id
                    WHERE mq.disciple_id = $1 AND mq.guild_id = $2
                    ORDER BY mq.created_at DESC
                ''', student.id, interaction.guild.id)
                student_quests = [dict(quest) for quest in student_quests]

            # Get student's points from leaderboard
            student_points = 0
            if hasattr(self.bot, 'leaderboard_manager'):
                try:
                    async with self.database.pool.acquire() as conn:
                        result = await conn.fetchval('''
                            SELECT points FROM leaderboard 
                            WHERE user_id = $1 AND guild_id = $2
                        ''', student.id, interaction.guild.id)
                        student_points = result or 0
                except Exception:
                    pass

            # Create progress embed
            embed = create_info_embed(
                f"📊 {student.display_name}'s Progress Report",
                f"Detailed training progress for your student"
            )

            # Basic Progress
            join_date = mentor_relationship['join_date']
            days_training = (datetime.now().date() - join_date.date()).days if join_date else 0

            basic_progress = f"**▸ Training Days:** {days_training} days\n"
            basic_progress += f"**▸ Current Points:** {student_points}\n"
            basic_progress += f"**▸ Role Awarded:** {'✅' if mentor_relationship.get('new_disciple_role_awarded') else '❌'}\n"
            basic_progress += f"**▸ Mentor Status:** ✅ Active (No starter requirements)"

            embed.add_field(
                name="━━━━━━━━━ Basic Progress ━━━━━━━━━",
                value=basic_progress,
                inline=True
            )

            # Quest Activity
            if student_quests:
                completed_quests = len([q for q in student_quests if q.get('status') == 'approved'])
                pending_quests = len([q for q in student_quests if q.get('status') == 'submitted'])
                total_quests = len(student_quests)

                quest_activity = f"**▸ Total Quests:** {total_quests}\n"
                quest_activity += f"**▸ Completed:** {completed_quests}\n"
                quest_activity += f"**▸ Pending Review:** {pending_quests}\n"
                if total_quests > 0:
                    quest_activity += f"**▸ Success Rate:** {(completed_quests/total_quests*100):.1f}%"
                else:
                    quest_activity += f"**▸ Success Rate:** 0%"
            else:
                quest_activity = "**▸ No mentor quests assigned yet**\n\nConsider creating your first quest for this student!"

            embed.add_field(
                name="━━━━━━━━━ Quest Activity ━━━━━━━━━",
                value=quest_activity,
                inline=True
            )

            # Recent Activity
            if student_quests:
                recent_quests = student_quests[:3]  # Last 3 quests
                recent_activity = ""
                for quest in recent_quests:
                    status = quest.get('status') or 'available'  # Default to available if no progress record
                    status_emoji = {"approved": "✅", "submitted": "🔄", "available": "📋", "rejected": "❌"}.get(status, "📋")
                    recent_activity += f"{status_emoji} {quest.get('title', 'Unknown Quest')}\n"

                embed.add_field(
                    name="━━━━━━━━━ Recent Quests ━━━━━━━━━",
                    value=recent_activity,
                    inline=False
                )

            # Pending Approvals
            pending_quests = [q for q in student_quests if q.get('status') == 'submitted']
            if pending_quests:
                pending_text = "**⏳ Quests awaiting your review:**\n"
                for quest in pending_quests:
                    quest_title = quest.get('title', 'Unknown Quest')[:30] + ('...' if len(quest.get('title', '')) > 30 else '')
                    pending_text += f"🔄 **{quest_title}**\n"
                    pending_text += f"   `ID: {quest.get('quest_id', 'unknown')}`\n"
                
                pending_text += f"\n💡 **Use:** `/approve_starter_quest quest_id:QUEST_ID student:{student.mention}`"
                
                embed.add_field(
                    name="━━━━━━━━━ 🔍 Needs Your Approval ━━━━━━━━━",
                    value=pending_text,
                    inline=False
                )
            elif student_quests:
                embed.add_field(
                    name="━━━━━━━━━ 🔍 Needs Your Approval ━━━━━━━━━",
                    value="✅ **All caught up!** No pending quest approvals.",
                    inline=False
                )

            # Recommendations
            recommendations = "**Suggested Actions:**\n"
            if not student_quests:
                recommendations += "• Create their first mentor quest\n"
            elif student_points < 50:
                recommendations += "• Assign point-earning quests to boost progression\n"
            else:
                recommendations += "• Continue with advanced training quests\n"

            recommendations += "• Check in with them regularly\n"
            recommendations += "• Celebrate their achievements!\n"
            recommendations += "• No starter quest requirements for mentored students"

            embed.add_field(
                name="━━━━━━━━━ Mentor Recommendations ━━━━━━━━━",
                value=recommendations,
                inline=False
            )

            await interaction.followup.send(embed=embed)
            logger.info(f"✅ {interaction.user.display_name} viewed progress for student {student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in student_progress command: {e}")
            embed = create_error_embed(
                "Progress Error",
                "Failed to load student progress",
                "Please try again or contact support."
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mentor_council", description="Access the private mentor discussion space and collaboration features")
    async def mentor_council(self, interaction: discord.Interaction):
        """Display mentor council collaboration features"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can access the mentor council",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get all mentors in the guild
            async with self.database.pool.acquire() as conn:
                mentor_results = await conn.fetch('''
                    SELECT user_id FROM mentors 
                    WHERE guild_id = $1 AND is_active = TRUE
                ''', interaction.guild.id)

            # Create mentor council embed
            embed = create_info_embed(
                "🤝 Mentor Council Hub",
                "Collaborate with fellow mentors and share knowledge",
                "Welcome to the exclusive mentor collaboration space"
            )

            # Active Mentors
            active_mentors = []
            for mentor_data in mentor_results:
                mentor = interaction.guild.get_member(mentor_data['user_id'])
                if mentor:
                    active_mentors.append(mentor.display_name)

            mentor_list = "\n".join([f"• {name}" for name in active_mentors[:10]])  # Show first 10
            if len(active_mentors) > 10:
                mentor_list += f"\n... and {len(active_mentors) - 10} more"

            embed.add_field(
                name=f"━━━━━━━━━ Active Mentors ({len(active_mentors)}) ━━━━━━━━━",
                value=mentor_list or "No other active mentors found",
                inline=False
            )

            # Mentor Tips and Best Practices
            mentor_tips = (
                "**💡 Proven Mentoring Strategies:**\n"
                "• Start with simple, achievable quests\n"
                "• Regular check-ins boost student engagement\n"
                "• Celebrate small wins to build confidence\n"
                "• Use quest templates for consistency\n"
                "• Share successful quest ideas with other mentors\n"
                "• Be patient - cultivation takes time!\n"
                "• Encourage students to help each other"
            )

            embed.add_field(
                name="━━━━━━━━━ Mentoring Best Practices ━━━━━━━━━",
                value=mentor_tips,
                inline=False
            )

            # Collaboration Features
            collaboration_features = (
                "**🤝 Available Collaboration Tools:**\n"
                "📋 `/share_quest` - Share successful quest ideas\n"
                "💬 `/mentor_broadcast` - Message your students\n"
                "📊 `/mentor_dashboard` - View your mentoring stats\n"
                "📚 `/quest_templates` - Access quest templates\n"
                "👥 `/student_progress` - Track individual students\n"
                "\n**💭 Discussion Topics:**\n"
                "• Student engagement strategies\n"
                "• Quest creation ideas\n"
                "• Handling difficult situations\n"
                "• Celebrating student achievements"
            )

            embed.add_field(
                name="━━━━━━━━━ Collaboration Tools ━━━━━━━━━",
                value=collaboration_features,
                inline=False
            )

            # Success Stories Template
            success_stories = (
                "**📈 Share Your Success Stories:**\n"
                "Help other mentors by sharing what works!\n"
                "\n**Template for sharing:**\n"
                "• **Student Challenge:** What problem did you face?\n"
                "• **Solution Used:** What approach worked?\n"
                "• **Results:** What was the outcome?\n"
                "• **Tips:** Advice for other mentors?\n"
                "\nPost your stories in the mentor discussion channels!"
            )

            embed.add_field(
                name="━━━━━━━━━ Success Stories ━━━━━━━━━",
                value=success_stories,
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ {interaction.user.display_name} accessed mentor council")

        except Exception as e:
            logger.error(f"❌ Error in mentor_council command: {e}")
            embed = create_error_embed(
                "Council Error",
                "Failed to load mentor council",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="share_quest", description="Share a successful quest template with other mentors")
    @app_commands.describe(
        quest_title="Title of the quest to share",
        quest_description="Description of what the quest involves",
        success_tips="Tips for other mentors on making this quest successful",
        recommended_points="Suggested point reward for this quest"
    )
    async def share_quest(
        self,
        interaction: discord.Interaction,
        quest_title: str,
        quest_description: str,
        success_tips: str = "",
        recommended_points: int = 10
    ):
        """Share a successful quest with other mentors"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can share quests",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create shared quest embed
            embed = create_success_embed(
                "Quest Template Shared!",
                f"**{interaction.user.display_name}** has shared a quest template",
                "This quest has been added to the mentor knowledge base"
            )

            embed.add_field(
                name="━━━━━━━━━ Quest Template ━━━━━━━━━",
                value=(
                    f"**📋 Title:** {quest_title}\n"
                    f"**💰 Suggested Points:** {recommended_points}\n"
                    f"**👤 Shared by:** {interaction.user.mention}\n"
                    f"**📅 Shared:** {datetime.now().strftime('%Y-%m-%d')}"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Description ━━━━━━━━━",
                value=quest_description[:1024],
                inline=False
            )

            if success_tips:
                embed.add_field(
                    name="━━━━━━━━━ Success Tips ━━━━━━━━━",
                    value=success_tips[:1024],
                    inline=False
                )

            usage_guide = (
                "**How to use this template:**\n"
                "1. Copy the title and description\n"
                "2. Use `/give_quest` command\n"
                "3. Customize for your specific student\n"
                "4. Apply the success tips shared by the mentor\n"
                "5. Award the suggested points upon completion"
            )

            embed.add_field(
                name="━━━━━━━━━ Usage Guide ━━━━━━━━━",
                value=usage_guide,
                inline=False
            )

            # Try to save to a shared quest database (optional feature)
            try:
                async with self.database.pool.acquire() as conn:
                    # Create shared quests table if it doesn't exist
                    await conn.execute('''
                        CREATE TABLE IF NOT EXISTS shared_mentor_quests (
                            id SERIAL PRIMARY KEY,
                            guild_id BIGINT NOT NULL,
                            shared_by_id BIGINT NOT NULL,
                            shared_by_name VARCHAR(255) NOT NULL,
                            title VARCHAR(500) NOT NULL,
                            description TEXT NOT NULL,
                            success_tips TEXT DEFAULT '',
                            recommended_points INTEGER DEFAULT 10,
                            shared_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            usage_count INTEGER DEFAULT 0
                        )
                    ''')

                    # Insert the shared quest
                    await conn.execute('''
                        INSERT INTO shared_mentor_quests 
                        (guild_id, shared_by_id, shared_by_name, title, description, success_tips, recommended_points)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ''', interaction.guild.id, interaction.user.id, interaction.user.display_name,
                        quest_title, quest_description, success_tips, recommended_points)

                    logger.info(f"✅ Saved shared quest '{quest_title}' by {interaction.user.display_name}")

            except Exception as db_error:
                logger.warning(f"⚠️ Could not save shared quest to database: {db_error}")

            await interaction.response.send_message(embed=embed)
            logger.info(f"✅ {interaction.user.display_name} shared quest template: {quest_title}")

        except Exception as e:
            logger.error(f"❌ Error in share_quest command: {e}")
            embed = create_error_embed(
                "Share Error",
                "Failed to share quest template",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mentor_tips", description="Get helpful mentoring advice and guidance for common situations")
    async def mentor_tips(self, interaction: discord.Interaction):
        """Display mentoring tips and guidance"""
        try:
            # Check if user is a mentor
            if not await self.is_mentor(interaction.user.id, interaction.guild.id):
                embed = create_error_embed(
                    "Access Denied",
                    "Only registered mentors can access mentoring tips",
                    "Contact an administrator to become a mentor."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create mentor tips embed
            embed = create_info_embed(
                "💡 Mentor Wisdom & Tips",
                "Proven strategies for effective student mentoring",
                "Learn from experienced mentors in the Heavenly Demon Sect"
            )

            # Getting Started Tips
            getting_started = (
                "**🌟 First Steps with New Students:**\n"
                "• Welcome them personally with a DM\n"
                "• Start with simple, achievable quests\n"
                "• Explain your mentoring style and expectations\n"
                "• Set regular check-in times\n"
                "• Be patient - everyone learns at different paces"
            )

            embed.add_field(
                name="━━━━━━━━━ Getting Started ━━━━━━━━━",
                value=getting_started,
                inline=False
            )

            # Quest Creation Tips
            quest_tips = (
                "**📋 Creating Effective Quests:**\n"
                "• Make objectives clear and specific\n"
                "• Include both easy and challenging elements\n"
                "• Tie quests to their interests (gaming, social, etc.)\n"
                "• Provide examples of what you're looking for\n"
                "• Set realistic deadlines and point rewards"
            )

            embed.add_field(
                name="━━━━━━━━━ Quest Creation ━━━━━━━━━",
                value=quest_tips,
                inline=False
            )

            # Engagement Strategies
            engagement_tips = (
                "**🎯 Boosting Student Engagement:**\n"
                "• Celebrate completions immediately\n"
                "• Share why each quest helps their growth\n"
                "• Create friendly competition between students\n"
                "• Ask about their interests and adapt accordingly\n"
                "• Use voice chat occasionally for personal connection"
            )

            embed.add_field(
                name="━━━━━━━━━ Engagement Strategies ━━━━━━━━━",
                value=engagement_tips,
                inline=False
            )

            # Handling Challenges
            challenge_tips = (
                "**🛠️ Common Challenges & Solutions:**\n"
                "• **Inactive Student:** Send encouraging check-ins, adjust quest difficulty\n"
                "• **Overwhelmed Student:** Break large quests into smaller steps\n"
                "• **Resistant Student:** Find out their interests and adapt\n"
                "• **Too Easy Quests:** Gradually increase complexity\n"
                "• **Lost Motivation:** Celebrate progress and set exciting goals"
            )

            embed.add_field(
                name="━━━━━━━━━ Handling Challenges ━━━━━━━━━",
                value=challenge_tips,
                inline=False
            )

            # Advanced Techniques
            advanced_tips = (
                "**🎓 Advanced Mentoring Techniques:**\n"
                "• Pair students for group quests\n"
                "• Create storyline quests that build on each other\n"
                "• Introduce them to other community members\n"
                "• Help them set long-term cultivation goals\n"
                "• Encourage them to mentor others eventually"
            )

            embed.add_field(
                name="━━━━━━━━━ Advanced Techniques ━━━━━━━━━",
                value=advanced_tips,
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"✅ {interaction.user.display_name} viewed mentor tips")

        except Exception as e:
            logger.error(f"❌ Error in mentor_tips command: {e}")
            embed = create_error_embed(
                "Tips Error",
                "Failed to load mentor tips",
                "Please try again or contact support."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    """Setup function for the cog"""
    pass  # This will be handled by the main bot