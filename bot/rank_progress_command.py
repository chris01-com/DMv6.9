
"""
Rank progress commands for checking requirements
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from bot.utils import create_success_embed, create_error_embed, create_info_embed, Colors, ENHANCED_RANK_REQUIREMENTS, get_rank_title_by_points, get_next_rank_info

logger = logging.getLogger(__name__)

class RankProgressCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Initialize when cog loads"""
        logger.info("✅ Rank progress commands cog loaded successfully")
    
    def get_components(self):
        """Get database and leaderboard manager components lazily"""
        database = None
        leaderboard_manager = None
        
        if hasattr(self.bot, 'sql_database') and self.bot.sql_database:
            database = self.bot.sql_database
        if hasattr(self.bot, 'leaderboard_manager') and self.bot.leaderboard_manager:
            leaderboard_manager = self.bot.leaderboard_manager
            
        return database, leaderboard_manager

    @app_commands.command(name='check_rank_requirements', description='Check your progress towards a specific rank')
    @app_commands.describe(
        rank="The rank you want to check requirements for"
    )
    @app_commands.choices(rank=[
        app_commands.Choice(name="Primordial Demon (2000 points)", value="1382602945752727613"),
        app_commands.Choice(name="Divine Demon (1500 points)", value="1391059979167072286"),
        app_commands.Choice(name="Ancient Demon (1250 points)", value="1391060071189971075"),
        app_commands.Choice(name="Arch Demon (750 points)", value="1268528848740290580"),
        app_commands.Choice(name="True Demon (500 points)", value="1308823860740624384"),
        app_commands.Choice(name="Great Demon (350 points)", value="1391059841505689680"),
        app_commands.Choice(name="Upper Demon (200 points)", value="1308823565881184348"),
        app_commands.Choice(name="Lower Demon (100 points)", value="1266826177163694181"),
    ])
    async def check_rank_requirements(self, interaction: discord.Interaction, rank: str):
        """Check your progress towards a specific rank"""
        try:
            # Ensure we have the necessary components
            database, leaderboard_manager = self.get_components()
            if not database or not leaderboard_manager:
                embed = create_error_embed("System Error", "Bot components not properly initialized.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Convert rank string to role ID
            try:
                role_id = int(rank)
            except ValueError:
                embed = create_error_embed("Invalid Rank", "The selected rank is not valid.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if role_id not in ENHANCED_RANK_REQUIREMENTS:
                embed = create_error_embed("Invalid Rank", "The selected rank is not available.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Find the target Discord role
            target_role = interaction.guild.get_role(role_id)
            if not target_role:
                embed = create_error_embed(
                    "Role Not Found", 
                    f"The Discord role was not found on this server."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if user already has this specific role
            if target_role in interaction.user.roles:
                embed = create_info_embed(
                    "Already Have This Rank",
                    f"You already have the **{target_role.name}** role!",
                    "You can check requirements for higher ranks."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get user's current points
            user_data = await leaderboard_manager.get_user_stats(interaction.guild.id, interaction.user.id)
            current_points = user_data.get('points', 0) if user_data else 0

            # Get rank requirements
            rank_info = ENHANCED_RANK_REQUIREMENTS[role_id]
            required_points = rank_info['points']
            
            # Check if user has required points
            if current_points < required_points:
                points_needed = required_points - current_points
                embed = create_error_embed(
                    f"Requirements Not Met for {target_role.name}",
                    f"You need {points_needed} more points.",
                    f"**Current Points:** {current_points}\n**Required Points:** {required_points}"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check previous rank requirement if any
            if rank_info.get('previous_rank'):
                previous_role_id = rank_info['previous_rank']
                previous_role = interaction.guild.get_role(previous_role_id)
                if previous_role and previous_role not in interaction.user.roles:
                    embed = create_error_embed(
                        f"Requirements Not Met for {target_role.name}",
                        f"You must have the previous rank first.",
                        f"**Missing Rank:** {previous_role.name}"
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            # Check quest requirements if any
            quest_requirements = rank_info.get('quest_requirements', {})
            if quest_requirements:
                # Get user's quest completions
                try:
                    async with database.pool.acquire() as conn:
                        for difficulty, required_count in quest_requirements.items():
                            completed_count = await conn.fetchval(
                                """SELECT COUNT(*) FROM quest_progress qp
                                   JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                                   WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'completed' 
                                   AND q.rank = $3""",
                                interaction.user.id, interaction.guild.id, difficulty
                            )
                            
                            if completed_count < required_count:
                                embed = create_error_embed(
                                    f"Requirements Not Met for {target_role.name}",
                                    f"You need to complete more {difficulty} quests.",
                                    f"**{difficulty} Quests Completed:** {completed_count}/{required_count}"
                                )
                                await interaction.response.send_message(embed=embed, ephemeral=True)
                                return
                except Exception as e:
                    logger.error(f"Error checking quest requirements: {e}")
                    embed = create_error_embed(
                        "System Error", 
                        "Unable to verify quest requirements. Please try again later.",
                        f"Error details: {str(e)}"
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return

            # User meets all requirements
            embed = create_success_embed(
                f"Ready for {target_role.name}!",
                "You meet all requirements for this rank.",
                f"You can now use `/getrank` to request this promotion.\n\n**Current Points:** {current_points}\n**Required Points:** {required_points}"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in check_rank_requirements: {e}")
            embed = create_error_embed("Command Error", f"An error occurred: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='my_rank_progress', description='See your current rank and progress towards the next rank')
    async def my_rank_progress(self, interaction: discord.Interaction):
        """Show user's current rank and progress to next rank"""
        try:
            # Ensure we have the necessary components
            database, leaderboard_manager = self.get_components()
            if not leaderboard_manager:
                embed = create_error_embed("System Error", "Leaderboard system not properly initialized.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get user's current points and rank with better error handling
            try:
                user_data = await leaderboard_manager.get_user_stats(interaction.guild.id, interaction.user.id)
                if user_data:
                    current_points = user_data.get('points', 0)
                    server_position = user_data.get('rank', 'Unranked')
                else:
                    current_points = 0
                    server_position = 'Unranked'
            except Exception as db_error:
                logger.error(f"Database error in my_rank_progress: {db_error}")
                current_points = 0
                server_position = 'Unranked'

            current_rank_title = get_rank_title_by_points(current_points, interaction.user)

            embed = create_info_embed(
                "📊 Your Rank Progress",
                f"**{interaction.user.display_name}**'s current standing in the Heavenly Demon Sect"
            )

            # Current status section
            status_value = (
                f"**▸ Current Rank:** {current_rank_title}\n"
                f"**▸ Points:** {current_points:,}\n"
                f"**▸ Server Position:** #{server_position}"
            )

            embed.add_field(
                name="━━━━━━━━━ Current Status ━━━━━━━━━",
                value=status_value,
                inline=False
            )

            # Get next rank using the advancement system
            try:
                next_rank_info = get_next_rank_info(current_points, interaction.user)
                
                if next_rank_info.get('max_rank_message'):
                    embed.add_field(
                        name="━━━━━━━━━ Achievement Complete ━━━━━━━━━",
                        value=next_rank_info['max_rank_message'],
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="━━━━━━━━━ Advancement Path ━━━━━━━━━",
                        value=f"**Target Rank:** {next_rank_info['next_rank']}\n**Points Required:** {next_rank_info['points_needed']}",
                        inline=False
                    )
            except Exception as rank_error:
                logger.error(f"Error getting next rank info: {rank_error}")
                embed.add_field(
                    name="━━━━━━━━━ Advancement Path ━━━━━━━━━",
                    value="**Status:** Unable to calculate advancement path",
                    inline=False
                )

            embed.set_thumbnail(url=interaction.user.display_avatar.url)

            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error in my_rank_progress: {e}")
            embed = create_error_embed("Command Error", "Failed to retrieve your statistics. Please try again later.")
            await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(RankProgressCommands(bot))
