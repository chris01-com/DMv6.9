import discord
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from bot.sql_database import SQLDatabase
from bot.utils import create_success_embed, create_info_embed, create_error_embed, get_qualifying_role_name
from bot.quest_manager import QuestManager

logger = logging.getLogger(__name__)

class GameMentorSelectionView(discord.ui.View):
    """View for students to choose mentors based on games they play"""

    def __init__(self, student: discord.Member, database: SQLDatabase, welcome_manager, games: dict = None):
        super().__init__(timeout=900)  # 15 minutes timeout
        self.student = student
        self.database = database
        self.welcome_manager = welcome_manager
        self.selection_made = False
        self.selected_game = None
        self.selected_mentor = None

        # Use provided games from database
        if games:
            self.GAMES = games
        else:
            # Use cultivation games from database with proper game keys
            self.GAMES = {
                "murim_cultivation": {"name": "Murim Cultivation", "emoji": "⚔️"},
                "soul_cultivation": {"name": "Soul Cultivation", "emoji": "👻"},
                "cultivation_era": {"name": "Cultivation Era", "emoji": "🌸"},
                "anime_spirit": {"name": "Anime Spirit", "emoji": "🔥"},
                "none": {"name": "No Mentor (Solo)", "emoji": ""}
            }

        # Populate the select menu options
        self.game_select.options = [
            discord.SelectOption(
                label=game_data['name'],
                value=game_key,
                description=f"Get a mentor who specializes in {game_data['name']}" if game_key != "none" else "Handle starter quests independently"
            ) for game_key, game_data in self.GAMES.items()
        ]

    @discord.ui.select(
        placeholder="Choose your cultivation path or go mentorless...",
        min_values=1,
        max_values=1,
        options=[]  # Will be populated dynamically in __init__
    )
    async def game_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        """Handle game selection"""
        if self.selection_made:
            await interaction.response.send_message("You have already made a selection!", ephemeral=True)
            return

        self.selection_made = True
        self.selected_game = select.values[0]

        # Disable the select menu
        select.disabled = True

        if self.selected_game == "none":
            # User chose to go mentorless
            await self._handle_mentorless_choice(interaction)
        else:
            # User chose a game - find mentors for that game
            await self._handle_game_mentor_choice(interaction)

    async def _handle_mentorless_choice(self, interaction: discord.Interaction):
        """Handle when student chooses to go without a mentor"""
        try:
            logger.info(f"🏃‍♂️ {self.student.display_name} chose to go without a mentor")

            # Assign starter quest to mentorless student
            success = await self.welcome_manager._assign_starter_quest_to_mentorless(self.student)
            if not success:
                embed = create_error_embed(
                    "Assignment Failed",
                    "Failed to assign starter quest. Please contact an administrator.",
                    "There was an error setting up your solo cultivation path."
                )
                await interaction.response.edit_message(embed=embed, view=None)
                return

            # Find starter quest for this user since they chose to go independent
            starter_quests = await self.welcome_manager._find_starter_quests(self.student.guild.id)

            # Assign starter quest to the user since they chose no mentor
            if starter_quests:
                await self.welcome_manager._assign_starter_quests(self.student, starter_quests)

                # Update database record with starter quest (only one now)
                quest_1_id = starter_quests[0]['quest_id'] if len(starter_quests) > 0 else None

                async with self.database.pool.acquire() as conn:
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET mentor_id = NULL, starter_quest_1 = $1, starter_quest_2 = NULL, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $2 AND guild_id = $3
                    ''', quest_1_id, self.student.id, self.student.guild.id)

            embed = create_success_embed(
                "Solo Cultivation Path Chosen!",
                f"You have chosen to walk the path of cultivation alone, {self.student.display_name}"
            )

            embed.add_field(
                name="Path Details",
                value="The sect respects those who forge their own way through determination and self-reliance.",
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Your Independent Journey ━━━━━━━━━",
                value=(
                    "**▸ Starter Quest:** Complete the hunting quest to earn Demon Apprentice role\n"
                    "**▸ Support:** Use general channels for questions\n"
                    "**▸ Progression:** Earn points and advance through the hierarchy\n"
                    "**▸ Future Mentorship:** You can always request a mentor later\n\n"
                    "**Remember:** True strength comes from within. The sect believes in your potential!"
                ),
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=None)

            # Send follow-up DM with mentorless instructions
            await self._send_mentorless_followup_dm()

            logger.info(f"✅ {self.student.display_name} chose to go mentorless and received starter quest")

        except Exception as e:
            logger.error(f"❌ Error handling mentorless choice: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def _send_mentorless_followup_dm(self):
        """Send follow-up DM explaining mentorless requirements"""
        try:
            embed = create_info_embed(
                "🎯 Your Solo Path Instructions",
                f"Welcome to independent cultivation, {self.student.display_name}!"
            )

            embed.add_field(
                name="━━━━━━━━━ Important Requirements ━━━━━━━━━",
                value=(
                    "**⚠️ As an independent cultivator, you must complete your starter quest first!**\n\n"
                    "▸ **Starter Quest Required:** You must finish your assigned starter quest before accessing other sect content\n"
                    "▸ **Access Restriction:** Most quests and activities are locked until starter completion\n"
                    "▸ **Progress Tracking:** Use `/my_quests` to view your current starter quest\n"
                    "▸ **Submission:** Use `/submit_starter` when you complete it\n\n"
                    "**This is different from mentored students who skip starter requirements!**"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Next Steps ━━━━━━━━━",
                value=(
                    "1️⃣ **Check Your Quest:** `/my_quests` to see your starter quest (ready to submit!)\n"
                    "2️⃣ **Quest Details:** `/quest_info <quest_id>` to get detailed quest information\n"
                    "3️⃣ **Complete Task:** Follow quest requirements carefully\n"
                    "4️⃣ **Submit Proof:** Use `/submit_quest <quest_id>` with screenshots/evidence\n"
                    "5️⃣ **Get Approved:** Wait for admin approval\n"
                    "6️⃣ **Unlock Content:** Once approved, all sect content becomes available!\n\n"
                    "💡 **Need help?** Ask questions in general channels!"
                ),
                inline=False
            )

            await self.student.send(embed=embed)
            logger.info(f"✅ Sent mentorless follow-up instructions to {self.student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error sending mentorless follow-up DM: {e}")

    async def _handle_game_mentor_choice(self, interaction: discord.Interaction):
        """Handle when student chooses a game and needs a mentor"""
        try:
            game_name = self.GAMES[self.selected_game]["name"]
            logger.info(f"🎯 {self.student.display_name} selected game: {self.selected_game} ({game_name})")

            # Find available mentors for this game
            available_mentors = await self._get_game_mentors(self.selected_game)
            logger.info(f"🔍 Found {len(available_mentors)} mentors for {game_name}: {[m.display_name for m in available_mentors]}")

            if not available_mentors:
                # No mentors available for this game - show explanation
                embed = create_info_embed(
                    f"No {game_name} Mentors Available",
                    f"Currently, there are no active mentors specializing in {game_name}",
                    "This specialization doesn't have any available mentors at the moment."
                )

                embed.add_field(
                    name="━━━━━━━━━ What You Can Do ━━━━━━━━━",
                    value=(
                        f"**▸ Choose Different Path:** Select another cultivation specialization\n"
                        f"**▸ Go Independent:** Complete your journey without a mentor\n"
                        f"**▸ Wait for Mentors:** Check back later when {game_name} mentors join\n"
                        f"**▸ Request Mentor:** Ask admins to add {game_name} mentors\n\n"
                        "Use the dropdown menu above to select a different specialization or choose 'No Mentor'."
                    ),
                    inline=False
                )

                embed.add_field(
                    name="━━━━━━━━━ Available Specializations ━━━━━━━━━",
                    value=(
                        "Check the dropdown menu for other cultivation paths that currently have active mentors available."
                    ),
                    inline=False
                )

                # Re-enable the select menu for new choice
                for item in self.children:
                    if isinstance(item, discord.ui.Select):
                        item.disabled = False

                self.selection_made = False
                await interaction.response.edit_message(embed=embed, view=self)
                return

            # Create mentor selection buttons
            mentor_view = SpecificMentorSelectionView(
                self.student, available_mentors, self.selected_game, self.database, self.welcome_manager
            )

            embed = create_info_embed(
                f"{game_name} Mentors Available!",
                f"Found {len(available_mentors)} available {game_name} mentors for you"
            )

            mentor_info = ""
            for i, mentor in enumerate(available_mentors, 1):
                # Get mentor's rank and stats
                mentor_points = await self.welcome_manager._get_user_points(mentor.id, self.student.guild.id)
                mentor_rank = get_qualifying_role_name(mentor_points, mentor) if mentor else "Sect Member"

                mentor_info += f"**{i}. {mentor.display_name}**\n"
                mentor_info += f"   ▸ **Rank:** {mentor_rank}\n"
                mentor_info += f"   ▸ **Specialization:** {game_name}\n"
                mentor_info += f"   ▸ **Points:** {mentor_points}\n"
                mentor_info += f"   ▸ **Capacity:** Unlimited\n\n"

            embed.add_field(
                name="━━━━━━━━━ Available Mentors ━━━━━━━━━",
                value=mentor_info,
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Choose Your Mentor ━━━━━━━━━",
                value=(
                    "**Select your preferred mentor using the buttons below:**\n\n"
                    "▸ **Quick Selection:** First available mentor\n"
                    "▸ **Specific Choice:** Pick your preferred mentor\n"
                    "▸ **Go Back:** Choose a different game\n\n"
                    "Your mentor will guide you through starter quests and help with game-specific advice!"
                ),
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=mentor_view)

        except Exception as e:
            logger.error(f"❌ Error handling game mentor choice: {e}")
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)

    async def _get_game_mentors(self, game: str) -> List[discord.Member]:
        """Get available mentors for a specific game"""
        try:
            async with self.database.pool.acquire() as conn:
                # First, get the game display name from the game key
                game_name = None
                if game in self.GAMES:
                    game_name = self.GAMES[game]["name"]
                else:
                    # Fallback: try to get from database
                    game_record = await conn.fetchrow('''
                        SELECT game_name FROM mentor_games
                        WHERE guild_id = $1 AND game_key = $2
                    ''', self.student.guild.id, game)
                    if game_record:
                        game_name = game_record['game_name']

                if not game_name:
                    logger.warning(f"⚠️ Could not find game name for key: {game}")
                    return []

                # Debug: Check all mentors first
                all_mentors = await conn.fetch('''
                    SELECT user_id, game_specialization, current_students, max_students, is_active
                    FROM mentors WHERE guild_id = $1
                ''', self.student.guild.id)
                logger.info(f"🔍 All mentors in database: {[(m['user_id'], m['game_specialization'], str(m['current_students']) + '/' + str(m['max_students']), m['is_active']) for m in all_mentors]}")

                # Get mentors who specialize in this specific game (no capacity limit)
                # Use both exact match and key-based match for better compatibility
                mentor_records = await conn.fetch('''
                    SELECT user_id, game_specialization FROM mentors
                    WHERE guild_id = $1 AND is_active = TRUE
                    AND (
                        game_specialization = $2 OR
                        game_specialization ILIKE $3 OR
                        game_specialization = $4
                    )
                ''', self.student.guild.id, game_name, f'%{game_name}%', game)

                logger.info(f"🎯 Game-specific mentors found: {[(m['user_id'], m['game_specialization']) for m in mentor_records]}")

                # If no game-specific mentors found, return empty list (no fallback)
                if not mentor_records:
                    logger.info(f"⚠️ No {game_name} mentors found - will show explanation to user")
                    return []

            available_mentors = []
            for record in mentor_records:
                mentor_member = self.student.guild.get_member(record['user_id'])
                if mentor_member and not mentor_member.bot:
                    available_mentors.append(mentor_member)

            return available_mentors[:5]  # Limit to 5 mentors max

        except Exception as e:
            logger.error(f"❌ Error getting game mentors: {e}")
            return []


class SpecificMentorSelectionView(discord.ui.View):
    """View for selecting a specific mentor from available options"""

    def __init__(self, student: discord.Member, mentors: List[discord.Member], game: str, database: SQLDatabase, welcome_manager):
        super().__init__(timeout=600)  # 10 minutes timeout
        self.student = student
        self.mentors = mentors
        self.game = game
        self.database = database
        self.welcome_manager = welcome_manager
        self.mentor_channel_manager = welcome_manager.mentor_channel_manager

        # Add mentor selection buttons (limit to 4 mentors + utility buttons)
        for i, mentor in enumerate(mentors[:4]):
            button = discord.ui.Button(
                label=f"{mentor.display_name}",
                style=discord.ButtonStyle.primary,
                custom_id=f"mentor_{mentor.id}"
            )
            button.callback = self._create_mentor_callback(mentor)
            self.add_item(button)

        # Add utility buttons
        if mentors:
            quick_button = discord.ui.Button(
                label="Quick Match",
                style=discord.ButtonStyle.success,
                emoji="⚡"
            )
            quick_button.callback = self._quick_match_callback
            self.add_item(quick_button)

        back_button = discord.ui.Button(
            label="Go Back",
            style=discord.ButtonStyle.secondary,
            emoji="↩️"
        )
        back_button.callback = self._go_back_callback
        self.add_item(back_button)

    def _create_mentor_callback(self, mentor: discord.Member):
        """Create callback function for specific mentor selection"""
        async def mentor_callback(interaction: discord.Interaction):
            await self._assign_mentor(interaction, mentor)
        return mentor_callback

    async def _quick_match_callback(self, interaction: discord.Interaction):
        """Quick match with first available mentor"""
        if self.mentors:
            await self._assign_mentor(interaction, self.mentors[0])
        else:
            await interaction.response.send_message("No mentors available for quick match.", ephemeral=True)

    async def _go_back_callback(self, interaction: discord.Interaction):
        """Go back to game selection"""
        # Load dynamic games for this guild
        guild_games = await self.welcome_manager.get_guild_games(self.student.guild.id)

        # Recreate the game selection view with dynamic games
        game_view = GameMentorSelectionView(self.student, self.database, self.welcome_manager, guild_games)

        embed = create_info_embed(
            "Choose Your Path",
            f"Select your preferred cultivation specialization for mentorship, {self.student.display_name}"
        )

        # Build dynamic game descriptions
        game_descriptions = []
        for game_key, game_data in guild_games.items():
            if game_key != "none":
                emoji = game_data.get('emoji', '')
                game_descriptions.append(f"**{emoji} {game_data['name']}:** Masters who specialize in {game_data['name']}")
            else:
                game_descriptions.append(f"**🚶 {game_data['name']}:** Walk the solo cultivation path independently")

        embed.add_field(
            name="━━━━━━━━━ Cultivation Specializations ━━━━━━━━━",
            value=(
                "\n".join(game_descriptions) +
                "\n\n**Choose wisely - your mentor will guide your early cultivation journey!**"
            ),
            inline=False
        )

        await interaction.response.edit_message(embed=embed, view=game_view)

    async def _assign_mentor(self, interaction: discord.Interaction, mentor: discord.Member):
        """Assign a specific mentor to the student"""
        try:
            game_name = self.GAMES.get(self.game, {}).get("name", "Unknown Game")

            # Record the assignment in database
            success = await self._record_mentor_assignment(self.student, mentor, self.game)
            if not success:
                embed = create_error_embed(
                    "Assignment Failed",
                    "Failed to assign mentor. Please try again or contact an administrator.",
                    "There was an error setting up your mentorship."
                )
                await interaction.response.edit_message(embed=embed, view=None)
                return

            # Create mentor channel if mentor channel manager is available
            mentor_channel = None
            if self.mentor_channel_manager:
                mentor_channel = await self.mentor_channel_manager.add_student_to_mentor_channel(
                    self.student, mentor
                )

            # Check if mentor is still active (no capacity limit)
            async with self.database.pool.acquire() as conn:
                mentor_info = await conn.fetchrow('''
                    SELECT current_students, max_students FROM mentors
                    WHERE user_id = $1 AND guild_id = $2 AND is_active = TRUE
                ''', mentor.id, self.student.guild.id)

                if not mentor_info:
                    await interaction.response.send_message(
                        f"{mentor.display_name} is no longer available. Please choose another mentor.",
                        ephemeral=True
                    )
                    return

                # Update welcome_automation record and clear starter quests for mentored users
                await conn.execute('''
                    UPDATE welcome_automation
                    SET starter_quest_1 = NULL, starter_quest_2 = NULL, last_activity = CURRENT_TIMESTAMP
                    WHERE user_id = $2 AND guild_id = $3
                ''', mentor.id, self.student.id, self.student.guild.id)

                # Update mentor's student count
                await conn.execute('''
                    UPDATE mentors
                    SET current_students = current_students + 1
                    WHERE user_id = $1 AND guild_id = $2
                ''', mentor.id, self.student.guild.id)

            # Send success message
            embed = create_success_embed(
                "Mentor Successfully Assigned!",
                f"You have been paired with **{mentor.display_name}** as your {game_name} mentor!"
            )

            embed.add_field(
                name="━━━━━━━━━ Mentorship Details ━━━━━━━━━",
                value=(
                    f"**▸ Mentor:** {mentor.mention}\n"
                    f"**▸ Specialization:** {game_name}\n"
                    f"**▸ Private Channel:** {mentor_channel.mention if mentor_channel else 'Creating...'}\n"
                    f"**▸ Next Steps:** Your mentor will reach out soon!\n\n"
                    "**Your mentor will help you with starter quests and provide game-specific guidance.**"
                ),
                inline=False
            )

            await interaction.response.edit_message(embed=embed, view=None)

            # Notify the mentor
            await self._notify_mentor_assignment(mentor, self.student, game_name, mentor_channel)

            # Send follow-up DM with mentored student instructions
            await self._send_mentored_followup_dm(mentor, game_name, mentor_channel)

            logger.info(f"✅ Assigned {mentor.display_name} as {game_name} mentor to {self.student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error assigning mentor: {e}")
            await interaction.response.send_message("An error occurred while assigning the mentor. Please try again.", ephemeral=True)

    async def _notify_mentor_assignment(self, mentor: discord.Member, student: discord.Member, game_name: str, channel: Optional[discord.TextChannel]):
        """Notify mentor about new student assignment"""
        try:
            embed = create_success_embed(
                "New Student Assigned!",
                f"You have been selected as a {game_name} mentor for **{student.display_name}**"
            )

            embed.add_field(
                name="━━━━━━━━━ Student Information ━━━━━━━━━",
                value=(
                    f"**▸ Student:** {student.mention}\n"
                    f"**▸ Game Focus:** {game_name}\n"
                    f"**▸ Private Channel:** {channel.mention if channel else 'Setting up...'}\n"
                    f"**▸ Joined:** {student.joined_at.strftime('%Y-%m-%d') if student.joined_at else 'Recently'}\n\n"
                    "**Your student chose you for your expertise! Guide them well and earn bonus points.**"
                ),
                inline=False
            )

            await mentor.send(embed=embed)
            logger.info(f"✅ Notified mentor {mentor.display_name} about new student {student.display_name}")

        except discord.Forbidden:
            logger.warning(f"⚠️ Could not DM mentor {mentor.display_name} about assignment")
        except Exception as e:
            logger.error(f"❌ Error notifying mentor: {e}")

    async def _send_mentored_followup_dm(self, mentor: discord.Member, game_name: str, mentor_channel: Optional[discord.TextChannel]):
        """Send follow-up DM explaining mentored student privileges"""
        try:
            embed = create_success_embed(
                "🎓 Mentored Student Privileges",
                f"Congratulations on being paired with mentor {mentor.display_name}!"
            )

            embed.add_field(
                name="━━━━━━━━━ Special Advantages ━━━━━━━━━",
                value=(
                    "**✅ No Starter Quest Requirements!**\n\n"
                    "▸ **Free Access:** You can accept any available quest immediately\n"
                    "▸ **Skip Restrictions:** No need to complete starter quests first\n"
                    "▸ **Instant Participation:** All sect content is unlocked for you\n"
                    "▸ **Mentor Guidance:** Your mentor will provide personalized training\n\n"
                    "**This is your reward for choosing the mentorship path!**"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Your Next Steps ━━━━━━━━━",
                value=(
                    f"1️⃣ **Visit Channel:** {mentor_channel.mention if mentor_channel else 'Your private channel'}\n"
                    f"2️⃣ **Introduce Yourself:** Say hello to {mentor.display_name}\n"
                    f"3️⃣ **Accept Quests:** Use `/my_quests` to see available quests\n"
                    f"4️⃣ **Stay Active:** Participate in sect activities\n"
                    f"5️⃣ **Earn Points:** Complete quests to advance in rank\n\n"
                    f"💡 **Your specialization:** {game_name} training focus"
                ),
                inline=False
            )

            await self.student.send(embed=embed)
            logger.info(f"✅ Sent mentored follow-up instructions to {self.student.display_name}")

        except Exception as e:
            logger.error(f"❌ Error sending mentored follow-up DM: {e}")

class WelcomeManager:
    """Manages welcome automation system for new members"""

    def __init__(self, database: SQLDatabase, quest_manager: QuestManager, mentor_channel_manager=None):
        self.database = database
        self.quest_manager = quest_manager
        self.mentor_channel_manager = mentor_channel_manager

        # Configuration
        self.MENTOR_USER_IDS = [1066149415129206835]  # Mentor user IDs (easily expandable)
        self.NEW_DISCIPLE_ROLE = 1389474689818296370  # Role awarded after completing starter quests
        self.WELCOME_TRIGGER_ROLE = 1268889388033642517  # Role that triggers welcome automation

        # Real Discord role hierarchy with cultivation lores from utils.py
        self.ROLE_HIERARCHY = {
            # Special Leadership Roles (Highest Tier)
            "demon_god": {
                "title": "Demon God",
                "points": "∞",
                "lore": "You have transcended all mortal and divine limitations. Reality bends to your indomitable will. Even concepts of good and evil bow before your transcendent might."
            },
            "heavenly_demon": {
                "title": "Heavenly Demon",
                "points": "∞",
                "lore": "The heavens themselves crack under the weight of your demonic authority. Gods whisper your name in terror. The nine heavens tremble as your demonic qi pierces through celestial barriers."
            },
            "supreme_demon": {
                "title": "Supreme Demon",
                "points": "∞",
                "lore": "Even the ancient demons kneel before your overwhelming presence. Fear follows in your wake. Your mere presence causes lesser demons to prostrate themselves in absolute submission."
            },
            "guardian": {
                "title": "Guardian",
                "points": "∞",
                "lore": "You are the eternal sentinel of our forbidden knowledge, keeper of secrets that drive mortals mad. Ancient oaths bind you to protect our darkest secrets from unworthy eyes."
            },
            "demon_council": {
                "title": "Demon Council",
                "points": "∞",
                "lore": "You sit upon the Throne of Bones, where your word becomes the law of the underworld. The Council of Shadows acknowledges your wisdom forged in the crucible of countless battles."
            },
            "demonic_commander": {
                "title": "Demonic Commander",
                "points": "∞",
                "lore": "You command legions of darkness with absolute authority. Your tactical brilliance and demonic prowess have earned you a position of unquestioned leadership among the sect's elite forces."
            },
            "young_master": {
                "title": "Young Master",
                "points": "∞",
                "lore": "Nobility flows through your dark bloodline - leadership is your birthright, power your inheritance. You command respect through both bloodline and proven strength."
            },

            # Core Disciple Tier (Advanced Cultivation)
            "divine_demon": {
                "title": "Divine Demon",
                "points": "1500",
                "lore": "The Inner Sanctum opens its doors to one who has bathed in the blood of a thousand enemies. Your cultivation has reached heights where divine authority flows through your veins."
            },
            "ancient_demon": {
                "title": "Ancient Demon",
                "points": "1250",
                "lore": "Your cultivation has reached heights where mountains crumble at your casual gesture. Ancient powers acknowledge your ascension to this legendary realm of demonic mastery."
            },
            "primordial_demon": {
                "title": "Primordial Demon",
                "points": "1000",
                "lore": "The sect's most guarded techniques are yours to command, earned through relentless sacrifice. You wield primordial forces that existed before creation itself."
            },

            # Inner Disciple Tier (Intermediate Cultivation)
            "arch_demon": {
                "title": "Arch Demon",
                "points": "750",
                "lore": "The forbidden arts flow through your meridians like liquid darkness. Your demonic aura terrifies even veteran cultivators. The weak flee at your approach."
            },
            "true_demon": {
                "title": "True Demon",
                "points": "500",
                "lore": "Your spirit weapon thirsts for battle, hungry for the qi of fallen foes. True demonic power courses through your being, marking you as elite among the sect."
            },
            "great_demon": {
                "title": "Great Demon",
                "points": "350",
                "lore": "The sect's secret archives unlock their mysteries to your battle-tested wisdom. You stand among the great, having proven yourself through countless trials."
            },

            # Outer Disciple Tier (Entry Cultivation)
            "upper_demon": {
                "title": "Upper Demon",
                "points": "200",
                "lore": "You step onto the path of darkness, leaving your mortal limitations behind. The first seal of demonic power breaks within your dantian, awakening your true potential."
            },
            "lower_demon": {
                "title": "Lower Demon",
                "points": "100",
                "lore": "Your foundation stone is laid with the blood of your enemies and the sweat of endless training. The forbidden qi flows through your meridians for the first time."
            },
            "new_disciple": {
                "title": "New Disciple",
                "points": "0",
                "lore": "From the blood-soaked training grounds, your dark journey begins. Each scar tells a story of relentless pursuit. Pain is your teacher, power is your reward."
            }
        }

    async def _get_quest_details(self, quest_id: str) -> Optional[Dict[str, Any]]:
        """Fetch detailed quest information from database"""
        try:
            async with self.database.pool.acquire() as conn:
                query = """
                    SELECT title, description, category, rank, reward, requirements, creator_id, guild_id
                    FROM quests
                    WHERE quest_id = $1
                """
                result = await conn.fetchrow(query, quest_id)

                if result:
                    return {
                        'title': result['title'],
                        'description': result['description'],
                        'category': result['category'],
                        'rank': result['rank'],
                        'reward': result['reward'],
                        'requirements': result['requirements'],
                        'creator_id': result['creator_id'],
                        'guild_id': result['guild_id']
                    }
                return None

        except Exception as e:
            logger.error(f"❌ Error fetching quest details for {quest_id}: {e}")
            return None

    async def get_guild_games(self, guild_id: int) -> dict:
        """Load games from database or return defaults"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get games from database
                games_result = await conn.fetch('''
                    SELECT game_key, game_name, emoji FROM mentor_games
                    WHERE guild_id = $1
                ''', guild_id)

                games = {}
                for row in games_result:
                    games[row['game_key']] = {
                        "name": row['game_name'],
                        "emoji": row['emoji']
                    }

                # Always add the "none" option for solo cultivation
                games["none"] = {"name": "No Mentor (Solo)", "emoji": ""}

                # If no custom games, return defaults with proper database keys
                if len(games) == 1:  # Only has "none"
                    games.update({
                        "murim_cultivation": {"name": "Murim Cultivation", "emoji": "⚔️"},
                        "soul_cultivation": {"name": "Soul Cultivation", "emoji": "👻"},
                        "cultivation_era": {"name": "Cultivation Era", "emoji": "🌸"},
                        "anime_spirit": {"name": "Anime Spirit", "emoji": "🔥"}
                    })

                return games

        except Exception as e:
            logger.error(f"❌ Error loading guild games: {e}")
            # Return default games if database error (with proper keys)
            return {
                "murim_cultivation": {"name": "Murim Cultivation", "emoji": "⚔️"},
                "soul_cultivation": {"name": "Soul Cultivation", "emoji": "👻"},
                "cultivation_era": {"name": "Cultivation Era", "emoji": "🌸"},
                "anime_spirit": {"name": "Anime Spirit", "emoji": "🔥"},
                "none": {"name": "No Mentor (Solo)", "emoji": ""}
            }

    async def initialize_welcome_tables(self):
        """Create welcome automation database tables"""
        try:
            async with self.database.pool.acquire() as conn:
                # Create new member onboarding tracking table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS welcome_automation (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        mentor_id BIGINT,
                        starter_quest_1 VARCHAR(255),
                        starter_quest_2 VARCHAR(255),
                        quest_1_completed BOOLEAN DEFAULT FALSE,
                        quest_2_completed BOOLEAN DEFAULT FALSE,
                        welcome_sent BOOLEAN DEFAULT FALSE,
                        reminder_sent BOOLEAN DEFAULT FALSE,
                        new_disciple_role_awarded BOOLEAN DEFAULT FALSE,
                        mentor_channel_id BIGINT,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (user_id, guild_id)
                    )
                ''')

                # Create mentor management table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS mentors (
                        user_id BIGINT NOT NULL,
                        guild_id BIGINT NOT NULL,
                        added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_active BOOLEAN DEFAULT TRUE,
                        mentor_channel_id BIGINT,
                        max_students INTEGER DEFAULT 10,
                        current_students INTEGER DEFAULT 0,
                        game_specialization VARCHAR(50) DEFAULT 'general',
                        PRIMARY KEY (user_id, guild_id)
                    )
                ''')

                # Add game_specialization column if it doesn't exist (for existing databases)
                await conn.execute('''
                    ALTER TABLE mentors
                    ADD COLUMN IF NOT EXISTS game_specialization VARCHAR(50) DEFAULT 'general'
                ''')

                # Create mentor games table
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

                # Initialize default mentor with unlimited capacity
                await conn.execute('''
                    INSERT INTO mentors (user_id, guild_id, max_students)
                    SELECT DISTINCT $1::BIGINT, guild_id::BIGINT, 999999
                    FROM leaderboard
                    WHERE guild_id IS NOT NULL
                    ON CONFLICT (user_id, guild_id) DO UPDATE SET max_students = 999999
                ''', int(self.MENTOR_USER_IDS[0]))

                # Update all existing mentors to have unlimited capacity
                await conn.execute('''
                    UPDATE mentors SET max_students = 999999 WHERE max_students < 999999
                ''')

                logger.info("✅ Welcome automation tables created successfully")

        except Exception as e:
            logger.error(f"❌ Error creating welcome automation tables: {e}")

    async def process_new_member(self, member: discord.Member, bot):
        """Process new member joining - complete welcome automation"""
        try:
            guild_id = member.guild.id
            user_id = member.id

            logger.info(f"🎯 Processing new member: {member.display_name} in {member.guild.name}")

            # Step 1: Find starter quests
            starter_quests = await self._find_starter_quests(guild_id)
            if len(starter_quests) < 1:
                logger.warning(f"⚠️ No starter quests found for guild {guild_id}, proceeding with welcome anyway")
                starter_quests = []  # Proceed with empty quest list

            # Step 2: Create database record with no mentor initially and NO starter quests yet
            await self._create_welcome_record(user_id, guild_id, None, [])

            # Step 3: Send welcome package with mentor choice FIRST (starter quests assigned based on choice)
            logger.info(f"📩 Attempting to send welcome package to {member.display_name} with {len(starter_quests)} starter quests")
            dm_sent = await self._send_welcome_package_with_mentor_choice(member, starter_quests)
            if not dm_sent:
                logger.warning(f"⚠️ Failed to send welcome DM to {member.display_name}")
                return False

            logger.info(f"✅ Welcome automation completed for {member.display_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Error processing new member {member.display_name}: {e}")
            return False

    async def _find_starter_quests(self, guild_id: int) -> List[Dict]:
        """Find default starter quests using specific quest IDs"""
        try:
            # Define default starter quest IDs
            starter_quest_ids = ['starter1', 'starter2', 'starter3', 'starter4', 'starter5']

            async with self.database.pool.acquire() as conn:
                starter_quests = []

                # Find all available starter quests for this guild
                for quest_id in starter_quest_ids:
                    quest = await conn.fetchrow('''
                        SELECT quest_id, title, description, reward
                        FROM quests
                        WHERE guild_id = $1 AND quest_id = $2 AND status = 'available'
                    ''', guild_id, quest_id)

                    if quest:
                        starter_quests.append(dict(quest))
                        logger.info(f"✅ Found starter quest {quest_id}: {quest['title']}")

                # If we found at least 1 starter quest, return up to 2
                if len(starter_quests) >= 1:
                    result = starter_quests[:2]  # Take up to 2 quests
                    logger.info(f"🔍 Using {len(result)} default starter quests for guild {guild_id}")
                    return result

                # If no specific starter quest found, fall back to easy hunting quest
                logger.warning(f"⚠️ Default starter quest not found for guild {guild_id}, using fallback method")

                # Fallback: Find easy hunting quest
                hunting_quest = await conn.fetchrow('''
                    SELECT quest_id, title, description, reward
                    FROM quests
                    WHERE guild_id = $1 AND rank = 'Easy' AND category = 'Hunting' AND status = 'available'
                    LIMIT 1
                ''', guild_id)

                fallback_quests = []
                if hunting_quest:
                    fallback_quests.append(dict(hunting_quest))

                logger.info(f"🔍 Found {len(fallback_quests)} fallback starter quest for guild {guild_id}")
                return fallback_quests

        except Exception as e:
            logger.error(f"❌ Error finding starter quests: {e}")
            return []

    async def _assign_mentor(self, member: discord.Member, bot) -> Optional[discord.Member]:
        """Send mentor selection request to all mentors and wait for first acceptance"""
        try:
            # Get all active mentors for this guild from database
            async with self.database.pool.acquire() as conn:
                mentor_records = await conn.fetch('''
                    SELECT user_id FROM mentors
                    WHERE guild_id = $1 AND is_active = TRUE
                ''', member.guild.id)

            if not mentor_records:
                logger.warning(f"⚠️ No mentors found in database for guild {member.guild.name}")
                return None

            # Get Discord member objects for mentors
            potential_mentors = []
            for record in mentor_records:
                mentor_member = member.guild.get_member(record['user_id'])
                if mentor_member and not mentor_member.bot:
                    potential_mentors.append(mentor_member)

            if not potential_mentors:
                logger.warning(f"⚠️ No valid mentor members found in guild {member.guild.name}")
                return None

            # Send mentor selection requests and wait for response
            selected_mentor = await self._send_mentor_selection_request(member, potential_mentors, bot)

            if selected_mentor:
                logger.info(f"👨‍£ Mentor {selected_mentor.display_name} accepted training {member.display_name}")
            else:
                logger.warning(f"⚠️ No mentor accepted training for {member.display_name}")

            return selected_mentor

        except Exception as e:
            logger.error(f"❌ Error in mentor assignment: {e}")
            return None

    async def _send_mentor_selection_request(self, member: discord.Member, mentors: List[discord.Member], bot) -> Optional[discord.Member]:
        """Send selection request to all mentors and return first to accept"""
        try:
            # Create mentor selection view
            selection_view = MentorSelectionView(member, self.database)

            # Create embed for mentor selection
            embed = create_info_embed(
                "New Student Needs Mentor!",
                f"**{member.display_name}** has joined the sect and needs guidance"
            )

            embed.add_field(
                name="━━━━━━━━━ Student Information ━━━━━━━━━",
                value=(
                    f"**▸ Student:** {member.mention}\n"
                    f"**▸ Join Date:** {member.joined_at.strftime('%Y-%m-%d %H:%M')}\n"
                    f"**▸ Account Age:** {(datetime.now(timezone.utc) - member.created_at).days} days\n"
                    f"**▸ Server:** {member.guild.name}\n\n"
                    f"**Training Includes:**\n"
                    f"▸ Guide through 2 starter quests\n"
                    f"▸ Private mentorship channel\n"
                    f"▸ Bonus points for successful guidance\n"
                    f"▸ Help with sect navigation and rules"
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Instructions ━━━━━━━━━",
                value=(
                    "**First mentor to click 'Accept Training' gets the student!**\n\n"
                    f"▸ **Accept:** Become {member.display_name}'s mentor\n"
                    f"▸ **Decline:** Pass on this opportunity\n"
                    f"▸ **Timeout:** 10 minutes (auto-decline)\n\n"
                    f"Once accepted, no other mentor can claim this student."
                ),
                inline=False
            )

            # Send selection request to all mentors via DM
            for mentor in mentors:
                try:
                    await mentor.send(embed=embed, view=selection_view)
                    logger.info(f"📩 Sent mentor selection request to {mentor.display_name}")
                except discord.Forbidden:
                    logger.warning(f"⚠️ Could not send mentor request to {mentor.display_name} (DMs disabled)")
                except Exception as e:
                    logger.error(f"❌ Error sending mentor request to {mentor.display_name}: {e}")

            # Wait for mentor selection (10 minutes timeout)
            try:
                selected_mentor = await asyncio.wait_for(selection_view.wait_for_selection(), timeout=600)

                if selected_mentor:
                    # Notify all other mentors that position was filled
                    await self._notify_mentors_position_filled(mentors, selected_mentor, member)

                return selected_mentor

            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Mentor selection timed out for {member.display_name} - continuing without mentor")
                # Notify mentors that request expired
                await self._notify_mentors_timeout(mentors, member)
                return None

        except Exception as e:
            logger.error(f"❌ Error in mentor selection request: {e}")
            return None

    async def _notify_mentors_position_filled(self, mentors: List[discord.Member], selected_mentor: discord.Member, student: discord.Member):
        """Notify all mentors that position was filled"""
        for mentor in mentors:
            if mentor.id != selected_mentor.id:  # Don't notify the selected mentor
                try:
                    embed = create_info_embed(
                        "Mentorship Position Filled",
                        f"The mentorship position for **{student.display_name}** has been filled",
                        f"**{selected_mentor.display_name}** was the first to accept and will be training this student."
                    )
                    await mentor.send(embed=embed)
                except:
                    pass  # Ignore errors for notifications

    async def _notify_mentors_timeout(self, mentors: List[discord.Member], student: discord.Member):
        """Notify mentors that request timed out"""
        for mentor in mentors:
            try:
                embed = create_error_embed(
                    "Mentorship Request Expired",
                    f"The mentorship request for **{student.display_name}** has expired",
                    "No mentor accepted within the 10-minute window. The student will proceed without a mentor."
                )
                await mentor.send(embed=embed)
            except:
                pass  # Ignore errors for notifications

    async def _create_welcome_record(self, user_id: int, guild_id: int, mentor: Optional[discord.Member], starter_quests: List[Dict]):
        """Create database record for new member"""
        try:
            mentor_id = mentor.id if mentor else None
            quest_1_id = starter_quests[0]['quest_id'] if len(starter_quests) > 0 else None
            quest_2_id = starter_quests[1]['quest_id'] if len(starter_quests) > 1 else None

            async with self.database.pool.acquire() as conn:
                # Check if record already exists
                existing = await conn.fetchrow('''
                    SELECT user_id FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', int(user_id), int(guild_id))

                if existing:
                    # Update existing record
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET mentor_id = $3, starter_quest_1 = $4, starter_quest_2 = $5, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', int(user_id), int(guild_id), mentor_id, str(quest_1_id) if quest_1_id else None, str(quest_2_id) if quest_2_id else None)
                else:
                    # Insert new record
                    await conn.execute('''
                        INSERT INTO welcome_automation
                        (user_id, guild_id, mentor_id, starter_quest_1, starter_quest_2)
                        VALUES ($1, $2, $3, $4, $5)
                    ''', int(user_id), int(guild_id), mentor_id, str(quest_1_id) if quest_1_id else None, str(quest_2_id) if quest_2_id else None)

            logger.info(f"💾 Created welcome record for user {user_id}")

        except Exception as e:
            logger.error(f"❌ Error creating welcome record: {e}")

    async def _send_welcome_package_with_mentor_choice(self, member: discord.Member, starter_quests: List[Dict]):
        """Send welcome DM with sect introduction and game-based mentor selection"""
        try:
            # Create welcome embed using existing design style
            embed = create_info_embed(
                "Welcome to the Heavenly Demon Sect!",
                f"Greetings, {member.display_name}! The shadows have whispered your name, and you have been chosen to join our eternal brotherhood of power."
            )

            # Add sect information at the top
            embed.add_field(
                name="━━━━━━━━━ About Our Sect ━━━━━━━━━",
                value=(
                    "The Heavenly Demon Sect(천마신교 天魔神敎) also known as the Demonic Cult (마교), Our Sect is regared as unorthodox sects. Our sects are usually termed as \"evil\" by orthodox sects. Disciples of our sects are trained in a \"kill or be killed, survival of the fittest. So, our ranks are given based on power and responsibilities."
                ),
                inline=False
            )


            # Add cultivation philosophy
            embed.add_field(
                name="━━━━━━━━━ Cultivation Philosophy ━━━━━━━━━",
                value=(
                    "**The Path of Demonic Ascension:**\n\n"
                    f"▸ **Start:** {self.ROLE_HIERARCHY['new_disciple']['lore'][:120]}...\n\n"
                    f"▸ **Advance:** Earn points through quest completion and sect contributions\n\n"
                    f"▸ **Ascend:** Each rank unlocks new powers and sect privileges\n\n"
                    f"▸ **Transcend:** Ultimate goal is achieving divine demonic authority"
                ),
                inline=False
            )


            # Load dynamic games for this guild
            guild_games = await self.get_guild_games(member.guild.id)

            # Add navigation help
            embed.add_field(
                name="━━━━━━━━━ Getting Started ━━━━━━━━━",
                value=(
                    "**Essential Commands:**\n"
                    "▸ `/my_quests` - View your assigned quests\n"
                    "▸ `/submit_quest` - Submit quest completion proof\n"
                    "▸ `/mystats` - Check your personal progress\n\n"
                    "**Important Channels:**\n"
                    "▸ Check pinned messages for channel guide\n"
                    "▸ Follow server rules and sect traditions\n"
                    "▸ Ask questions in general channels"
                ),
                inline=False
            )

            # Create game-based mentor selection view with dynamic games
            mentor_selection_view = GameMentorSelectionView(member, self.database, self, guild_games)

            # Send DM with mentor selection interface
            dm_success = False

            # First attempt - standard DM with interactive selection
            try:
                await member.send(embed=embed, view=mentor_selection_view)
                logger.info(f"✅ Sent game-based mentor selection DM to {member.display_name}")
                dm_success = True

            except discord.Forbidden as forbidden_error:
                logger.warning(f"⚠️ First DM attempt failed for {member.display_name}: {forbidden_error}")

                # Second attempt - try creating DM channel first
                try:
                    dm_channel = await member.create_dm()
                    await dm_channel.send(embed=embed, view=mentor_selection_view)
                    logger.info(f"✅ Sent game-based mentor selection DM to {member.display_name} via direct DM channel creation")
                    dm_success = True

                except discord.Forbidden:
                    logger.warning(f"⚠️ Second DM attempt also failed for {member.display_name} - using fallback")
                    dm_success = False
                except Exception as retry_error:
                    logger.warning(f"⚠️ DM retry failed for {member.display_name}: {retry_error} - using fallback")
                    dm_success = False

            except Exception as dm_error:
                logger.error(f"❌ Unexpected DM error for {member.display_name}: {dm_error}")

                # Third attempt - force try with a simple message first
                try:
                    await member.send("🎯 Testing DM connection...")
                    await asyncio.sleep(0.5)  # Small delay
                    await member.send(embed=embed, view=mentor_selection_view)
                    logger.info(f"✅ Sent game-based mentor selection DM to {member.display_name} after connection test")
                    dm_success = True
                except:
                    logger.warning(f"⚠️ All DM attempts failed for {member.display_name} - using fallback")
                    dm_success = False

            # If DM failed, try to send to a public channel as fallback
            if not dm_success:
                try:
                    # Try to find notification channel or system channel
                    notification_channel = None
                    async with self.database.pool.acquire() as conn:
                        channel_config = await conn.fetchrow('''
                            SELECT notification_channel FROM channel_config
                            WHERE guild_id = $1
                        ''', member.guild.id)

                    if channel_config and channel_config['notification_channel']:
                        notification_channel = member.guild.get_channel(channel_config['notification_channel'])

                    if not notification_channel:
                        notification_channel = member.guild.system_channel

                    if notification_channel:
                        # Add mention at top for fallback notification
                        fallback_embed = create_info_embed(
                            f"Welcome {member.display_name}!",
                            f"📩 **DMs appear to be disabled - welcome message sent here instead!**\n\n" + embed.description
                        )

                        # Copy all fields from original embed
                        for field in embed.fields:
                            fallback_embed.add_field(name=field.name, value=field.value, inline=field.inline)

                        await notification_channel.send(content=f"{member.mention}", embed=fallback_embed)
                        logger.info(f"✅ Sent fallback welcome to {notification_channel.name} for {member.display_name}")
                        dm_success = True

                except Exception as fallback_error:
                    logger.error(f"❌ Fallback notification also failed for {member.display_name}: {fallback_error}")

            # Mark welcome as sent if either DM or fallback succeeded
            if dm_success:
                try:
                    async with self.database.pool.acquire() as conn:
                        await conn.execute('''
                            UPDATE welcome_automation
                            SET welcome_sent = TRUE
                            WHERE user_id = $1 AND guild_id = $2
                        ''', member.id, member.guild.id)
                except Exception as db_error:
                    logger.error(f"❌ Error updating welcome_sent status: {db_error}")

            return dm_success

        except Exception as e:
            logger.error(f"❌ Error sending welcome package: {e}")
            return False

    async def _get_user_points(self, user_id: int, guild_id: int) -> int:
        """Get user's current points from leaderboard"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchrow('''
                    SELECT points FROM leaderboard
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)
                return result['points'] if result else 0
        except Exception as e:
            logger.error(f"❌ Error getting user points: {e}")
            return 0

    async def _get_quest_details(self, quest_id: str) -> Optional[Dict]:
        """Get complete quest details from database"""
        try:
            async with self.database.pool.acquire() as conn:
                quest = await conn.fetchrow('''
                    SELECT * FROM quests WHERE quest_id = $1
                ''', quest_id)
                return dict(quest) if quest else None
        except Exception as e:
            logger.error(f"❌ Error getting quest details: {e}")
            return None

    async def _create_mentor_channel(self, student: discord.Member, mentor: discord.Member, bot) -> Optional[discord.TextChannel]:
        """Create private mentorship channel"""
        try:
            guild = student.guild

            # Create channel name
            channel_name = f"mentorship-{student.display_name}-{mentor.display_name}".lower().replace(" ", "-")

            # Set up permissions
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                student: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                mentor: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True)
            }

            # Create the channel
            channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                topic=f"Private mentorship channel for {student.display_name} and mentor {mentor.display_name}",
                reason="Automated mentorship channel creation"
            )

            # Update database with channel info
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE welcome_automation
                    SET mentor_channel_id = $1
                    WHERE user_id = $2 AND guild_id = $3
                ''', channel.id, student.id, guild.id)

                await conn.execute('''
                    UPDATE mentors
                    SET mentor_channel_id = $1
                    WHERE user_id = $2 AND guild_id = $3
                ''', channel.id, mentor.id, guild.id)

            # Send welcome message to the channel
            welcome_embed = create_success_embed(
                "Mentorship Channel Created!",
                f"Welcome to your private mentorship space!"
            )

            welcome_embed.add_field(
                name="━━━━━━━━━ Mentorship Guidelines ━━━━━━━━━",
                value=(
                    f"**👤 Student:** {student.mention}\n"
                    f"**🎓 Mentor:** {mentor.mention}\n\n"
                    "**▸ Purpose:** Guide the student through starter quests and early cultivation\n"
                    "**▸ Privacy:** This channel is private between mentor and student\n"
                    "**▸ Goals:** Complete starter quests and learn sect basics\n"
                    "**▸ Rewards:** Mentors earn bonus points for successful guidance\n\n"
                    "**Good luck on your cultivation journey together!**"
                ),
                inline=False
            )

            await channel.send(embed=welcome_embed)

            logger.info(f"✅ Created mentorship channel {channel.name} for {student.display_name} and {mentor.display_name}")
            return channel

        except Exception as e:
            logger.error(f"❌ Error creating mentor channel: {e}")
            return None

    async def _assign_starter_quests(self, member: discord.Member, starter_quests: List[Dict]):
        """Auto-assign starter quests to new member - ready to submit directly"""
        try:
            from bot.models import QuestProgress, ProgressStatus
            from datetime import datetime

            for quest in starter_quests:
                try:
                    # Create quest progress entry directly as ACCEPTED (skip the accept step)
                    progress = QuestProgress(
                        quest_id=quest['quest_id'],
                        user_id=member.id,
                        guild_id=member.guild.id,
                        status=ProgressStatus.ACCEPTED,
                        accepted_at=datetime.now(),
                        channel_id=0
                    )

                    # Save to database
                    await self.quest_manager.database.save_quest_progress(progress)
                    logger.info(f"✅ Auto-assigned starter quest {quest['title']} to {member.display_name} - Ready to submit!")

                except Exception as quest_error:
                    logger.error(f"❌ Exception in auto-assigning quest {quest['quest_id']}: {quest_error}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")

        except Exception as e:
            logger.error(f"❌ Error in starter quest assignment: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")



    async def _notify_mentor(self, mentor: discord.Member, new_member: discord.Member,
                           mentor_channel: Optional[discord.TextChannel], starter_quests: List[Dict]):
        """Notify mentor about new mentee assignment"""
        try:
            # Create notification embed
            embed = create_info_embed(
                "New Mentee Assigned!",
                f"You have been assigned as a mentor to help guide a new sect member."
            )

            embed.add_field(
                name="━━━━━━━━━ Mentee Information ━━━━━━━━━",
                value=(
                    f"**▸ New Member:** {new_member.display_name}\n"
                    f"**▸ Joined:** {new_member.joined_at.strftime('%Y-%m-%d %H:%M') if new_member.joined_at else 'Recently'}\n"
                    f"**▸ Discord ID:** {new_member.id}\n"
                ),
                inline=False
            )

            if starter_quests:
                quest_list = ""
                for i, quest in enumerate(starter_quests, 1):
                    quest_list += f"**{i}. {quest['title']}**\n"
                    quest_list += f"   ▸ {quest['description'][:80]}...\n\n"

                embed.add_field(
                    name="━━━━━━━━━ Assigned Starter Quests ━━━━━━━━━",
                    value=quest_list,
                    inline=False
                )

            embed.add_field(
                name="━━━━━━━━━ Mentorship Responsibilities ━━━━━━━━━",
                value=(
                    "**▸ Guide them through starter quests**\n"
                    "**▸ Answer questions about sect operations**\n"
                    "**▸ Help them understand the hierarchy system**\n"
                    "**▸ Encourage active participation**\n\n"
                    "**Mentor Rewards:**\n"
                    "▸ Bonus points for successful mentee completion\n"
                    "▸ Recognition in sect announcements"
                ),
                inline=False
            )

            if mentor_channel:
                embed.add_field(
                    name="━━━━━━━━━ Communication Channel ━━━━━━━━━",
                    value=f"Private mentorship channel: {mentor_channel.mention}",
                    inline=False
                )

            # Send DM to mentor
            try:
                await mentor.send(embed=embed)
                logger.info(f"✅ Sent mentor notification to {mentor.display_name}")
            except discord.Forbidden:
                logger.warning(f"⚠️ Could not send DM to mentor {mentor.display_name}")

        except Exception as e:
            logger.error(f"❌ Error notifying mentor: {e}")

    async def _update_mentor_channel(self, user_id: int, guild_id: int, channel_id: int):
        """Update welcome record with mentor channel ID"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE welcome_automation
                    SET mentor_channel_id = $1
                    WHERE user_id = $2 AND guild_id = $3
                ''', channel_id, user_id, guild_id)

        except Exception as e:
            logger.error(f"❌ Error updating mentor channel: {e}")

    async def check_quest_completion(self, user_id: int, guild_id: int, quest_id: str, bot):
        """Check if user completed starter quest and award role if both completed"""
        try:
            logger.info(f"🔍 Checking quest completion for user {user_id}, quest {quest_id}")

            async with self.database.pool.acquire() as conn:
                # Get welcome record
                record = await conn.fetchrow('''
                    SELECT * FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)

                if not record:
                    logger.info(f"⚠️ No welcome record found for user {user_id}")
                    return False

                logger.info(f"📋 Welcome record found: starter1={record['starter_quest_1']}, starter2={record['starter_quest_2']}")
                logger.info(f"📊 Current status: quest1_done={record['quest_1_completed']}, quest2_done={record['quest_2_completed']}, role_awarded={record['new_disciple_role_awarded']}")

                # Check which quest was completed
                quest_1_completed = record['quest_1_completed']
                quest_2_completed = record['quest_2_completed']

                # Update completion status
                if quest_id == record['starter_quest_1']:
                    quest_1_completed = True
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET quest_1_completed = TRUE, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', user_id, guild_id)
                    logger.info(f"✅ Updated starter quest 1 completion for user {user_id}")
                elif quest_id == record['starter_quest_2']:
                    quest_2_completed = True
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET quest_2_completed = TRUE, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', user_id, guild_id)
                    logger.info(f"✅ Updated starter quest 2 completion for user {user_id}")
                else:
                    logger.info(f"ℹ️ Quest {quest_id} is not a tracked starter quest for user {user_id}")
                    return False

                # Check if starter quest completed
                logger.info(f"🎯 Checking completion: quest1={quest_1_completed}, role_not_awarded={not record['new_disciple_role_awarded']}")
                if quest_1_completed and not record['new_disciple_role_awarded']:
                    logger.info(f"🎉 Starter quest completed! Awarding role to user {user_id}")
                    await self._award_new_disciple_role(user_id, guild_id, bot)
                    return True

        except Exception as e:
            logger.error(f"❌ Error checking quest completion: {e}")

        return False

    async def _award_new_disciple_role(self, user_id: int, guild_id: int, bot):
        """Award New Disciple role after completing starter quest"""
        try:
            # Get guild and member
            guild = bot.get_guild(guild_id)
            if not guild:
                return

            member = guild.get_member(user_id)
            if not member:
                return

            # Get the role
            role = guild.get_role(self.NEW_DISCIPLE_ROLE)
            if not role:
                logger.error(f"❌ New Disciple role {self.NEW_DISCIPLE_ROLE} not found")
                return

            # Award role
            await member.add_roles(role, reason="Completed starter quest")

            # Update database
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE welcome_automation
                    SET new_disciple_role_awarded = TRUE
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)

            # Get mentor and channel info for congratulations
            mentor_info = await self._get_mentor_info(user_id, guild_id)

            # Send congratulations
            await self._send_completion_congratulations(member, role, mentor_info)

            logger.info(f"✅ Awarded Demon Apprentice role to {member.display_name}")

        except Exception as e:
            logger.error(f"❌ Error awarding Demon Apprentice role: {e}")

    async def _get_mentor_info(self, user_id: int, guild_id: int) -> dict:
        """Get mentor and channel information for a user"""
        try:
            async with self.database.pool.acquire() as conn:
                record = await conn.fetchrow('''
                    SELECT mentor_id, mentor_channel_id
                    FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)

                if record:
                    return {
                        'mentor_user_id': record['mentor_id'],
                        'mentor_channel_id': record['mentor_channel_id']
                    }
                return {}
        except Exception as e:
            logger.error(f"❌ Error getting mentor info: {e}")
            return {}

    async def _send_completion_congratulations(self, member: discord.Member, role: discord.Role, mentor_info: dict = None):
        """Send congratulations message for completing starter quests"""
        try:
            logger.info(f"🎉 Sending completion congratulations to {member.display_name}")

            embed = create_success_embed(
                "Starter Quest Completed!",
                f"Congratulations {member.display_name}! You have successfully completed your introduction to the Heavenly Demon Sect."
            )

            # Prepare mentor information
            mentor_text = ""
            if mentor_info and mentor_info.get('mentor_user_id') and mentor_info.get('mentor_channel_id'):
                mentor_user = member.guild.get_member(mentor_info['mentor_user_id'])
                mentor_channel = member.guild.get_channel(mentor_info['mentor_channel_id'])

                if mentor_user:
                    mentor_text = f"**▸ Assigned Mentor:** {mentor_user.display_name}\n"
                    logger.info(f"🧑‍🏫 Mentor found: {mentor_user.display_name}")

                if mentor_channel:
                    mentor_text += f"**▸ Mentor Channel:** {mentor_channel.mention}\n"
                    logger.info(f"📢 Mentor channel found: {mentor_channel.name}")
            else:
                logger.warning(f"⚠️ No mentor info available for {member.display_name}")

            embed.add_field(
                name="━━━━━━━━━ Achievement Unlocked ━━━━━━━━━",
                value=(
                    f"**▸ Role Awarded:** {role.mention}\n"
                    f"**▸ Status:** Official Sect Member\n"
                    f"{mentor_text}"
                    f"**▸ Next Steps:** Continue with regular sect quests\n\n"
                    f"You are now a recognized member of the Heavenly Demon Sect! "
                    f"Your dedication to completing the starter quest shows promise for your cultivation journey."
                ),
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Continue Your Journey ━━━━━━━━━",
                value=(
                    "**▸ Explore:** Use `/list_quests` to find new challenges\n"
                    "**▸ Advance:** Earn points to unlock higher sect ranks\n"
                    "**▸ Participate:** Join team quests and sect activities\n"
                    "**▸ Grow:** Build your reputation within the sect\n\n"
                    "The path of cultivation is endless. Continue to prove your worth!"
                ),
                inline=False
            )

            # Send DM
            try:
                await member.send(embed=embed)
                logger.info(f"✅ Sent completion congratulations DM to {member.display_name}")
            except discord.Forbidden:
                logger.warning(f"⚠️ DM failed for {member.display_name}, trying public channel")
                # If DM fails, try to send in a public channel
                if member.guild.system_channel:
                    await member.guild.system_channel.send(f"{member.mention}", embed=embed)
                    logger.info(f"✅ Sent completion congratulations in public channel for {member.display_name}")

        except Exception as e:
            logger.error(f"❌ Error sending completion congratulations: {e}")

    async def send_48_hour_reminders(self, bot):
        """Send reminders to members who haven't completed starter quest in 48 hours"""
        try:
            cutoff_time = datetime.now() - timedelta(hours=48)

            async with self.database.pool.acquire() as conn:
                # Find members who need reminders
                records = await conn.fetch('''
                    SELECT * FROM welcome_automation
                    WHERE join_date < $1
                    AND quest_1_completed = FALSE
                    AND new_disciple_role_awarded = FALSE
                    AND reminder_sent = FALSE
                ''', cutoff_time)

                for record in records:
                    try:
                        guild = bot.get_guild(record['guild_id'])
                        if not guild:
                            continue

                        member = guild.get_member(record['user_id'])
                        if not member:
                            continue

                        await self._send_reminder_message(member, record)

                        # Mark reminder as sent
                        await conn.execute('''
                            UPDATE welcome_automation
                            SET reminder_sent = TRUE
                            WHERE user_id = $1 AND guild_id = $2
                        ''', record['user_id'], record['guild_id'])

                    except Exception as member_error:
                        logger.error(f"❌ Error sending reminder to member {record['user_id']}: {member_error}")

        except Exception as e:
            logger.error(f"❌ Error in 48-hour reminder system: {e}")

    async def _send_reminder_message(self, member: discord.Member, record):
        """Send gentle reminder message to member"""
        try:
            embed = create_info_embed(
                "Sect Quest Reminder",
                f"Greetings {member.display_name}, we noticed you haven't completed your starter quest yet."
            )

            quest_status = ""
            if not record['quest_1_completed']:
                quest_status += "▸ **Starter Quest:** Incomplete\n"
            else:
                quest_status += "▸ **Starter Quest:** ✅ Complete\n"

            embed.add_field(
                name="━━━━━━━━━ Quest Progress ━━━━━━━━━",
                value=quest_status + "\nComplete the quest to earn your first sect role!",
                inline=False
            )

            embed.add_field(
                name="━━━━━━━━━ Need Help? ━━━━━━━━━",
                value=(
                    "**▸ Check Progress:** Use `/my_quests` to see your assignments\n"
                    "**▸ Submit Work:** Use `/submit_quest` when ready\n"
                    "**▸ Ask Questions:** Reach out to your mentor or ask in general chat\n\n"
                    "The sect believes in your potential - don't give up on your cultivation journey!"
                ),
                inline=False
            )

            try:
                await member.send(embed=embed)
                logger.info(f"✅ Sent 48-hour reminder to {member.display_name}")
            except discord.Forbidden:
                logger.warning(f"⚠️ Could not send reminder DM to {member.display_name}")

        except Exception as e:
            logger.error(f"❌ Error sending reminder message: {e}")

    async def _get_user_points(self, user_id: int, guild_id: int) -> int:
        """Get user's points from the database"""
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetchval('''
                    SELECT points FROM leaderboard
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)

                return result or 0  # Return 0 if user not found

        except Exception as e:
            logger.error(f"❌ Error getting user points: {e}")
            return 0

    async def add_mentor(self, user_id: int, guild_id: int, game_specialization: str = "general") -> bool:
        """Add a new mentor to the database"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO mentors (user_id, guild_id, game_specialization, max_students)
                    VALUES ($1, $2, $3, 999999)
                    ON CONFLICT (user_id, guild_id) DO UPDATE SET
                    is_active = TRUE,
                    game_specialization = EXCLUDED.game_specialization,
                    max_students = 999999,
                    added_date = CURRENT_TIMESTAMP
                ''', user_id, guild_id, game_specialization)

            logger.info(f"✅ Added mentor {user_id} for guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error adding mentor: {e}")
            return False

    async def remove_mentor(self, user_id: int, guild_id: int) -> bool:
        """Remove/deactivate a mentor from the database"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    UPDATE mentors
                    SET is_active = FALSE
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, guild_id)

            logger.info(f"✅ Removed mentor {user_id} for guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error removing mentor: {e}")
            return False

    async def list_mentors(self, guild_id: int) -> List[Dict]:
        """Get list of all active mentors for a guild"""
        try:
            async with self.database.pool.acquire() as conn:
                mentors = await conn.fetch('''
                    SELECT user_id, added_date, game_specialization
                    FROM mentors
                    WHERE guild_id = $1 AND is_active = TRUE
                    ORDER BY added_date ASC
                ''', guild_id)

            return [dict(mentor) for mentor in mentors]

        except Exception as e:
            logger.error(f"❌ Error listing mentors: {e}")
            return []

    async def _record_mentor_assignment(self, student: discord.Member, mentor: discord.Member, game: str):
        """Record mentor assignment in database"""
        try:
            async with self.database.pool.acquire() as conn:
                # Check if record exists
                existing = await conn.fetchrow('''
                    SELECT user_id FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', student.id, student.guild.id)

                if existing:
                    # Update existing record
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET mentor_id = $3, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', student.id, student.guild.id, mentor.id)
                else:
                    # Insert new record
                    await conn.execute('''
                        INSERT INTO welcome_automation (user_id, guild_id, mentor_id)
                        VALUES ($1, $2, $3)
                    ''', student.id, student.guild.id, mentor.id)

            logger.info(f"✅ Recorded mentor assignment: {mentor.display_name} -> {student.display_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Error recording mentor assignment: {e}")
            return False

    async def _assign_starter_quest_to_mentorless(self, student: discord.Member):
        """Assign starter quest to a mentorless student"""
        try:
            # Record in welcome automation
            async with self.database.pool.acquire() as conn:
                # Check if record exists
                existing = await conn.fetchrow('''
                    SELECT user_id FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', student.id, student.guild.id)

                if existing:
                    # Update existing record
                    await conn.execute('''
                        UPDATE welcome_automation
                        SET mentor_id = NULL, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', student.id, student.guild.id)
                else:
                    # Insert new record
                    await conn.execute('''
                        INSERT INTO welcome_automation (user_id, guild_id, mentor_id)
                        VALUES ($1, $2, NULL)
                    ''', student.id, student.guild.id)

            logger.info(f"✅ Assigned starter quest to mentorless student {student.display_name}")
            return True

        except Exception as e:
            logger.error(f"❌ Error assigning starter quest to mentorless student: {e}")
            return False