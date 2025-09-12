import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

class EnhancedQuestCommands(commands.Cog):
    """Commands for enhanced quest features"""
    
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command(name="enhanced_search", description="Advanced quest search with multiple filters")
    @app_commands.describe(
        query="Search text (title, description, requirements, rewards)",
        rank="Quest difficulty rank",
        category="Quest category",
        creator="Quest creator (mention user)",
        min_reward="Minimum reward points",
        max_reward="Maximum reward points"
    )
    async def search_quests(
        self, 
        interaction: discord.Interaction,
        query: Optional[str] = None,
        rank: Optional[str] = None,
        category: Optional[str] = None,
        creator: Optional[discord.Member] = None,
        min_reward: Optional[int] = None,
        max_reward: Optional[int] = None
    ):
        """Search for quests with advanced filters"""
        await interaction.response.defer()
        
        try:
            search_params = {}
            if query:
                search_params['query'] = query
            if rank:
                search_params['rank'] = rank
            if category:
                search_params['category'] = category
            if creator:
                search_params['creator_id'] = creator.id
            if min_reward:
                search_params['min_reward'] = min_reward
            if max_reward:
                search_params['max_reward'] = max_reward
            
            results = await self.bot.quest_search_system.search_quests(
                interaction.guild_id, **search_params
            )
            
            if not results:
                await interaction.followup.send("🔍 No quests found matching your criteria.")
                return
            
            embed = discord.Embed(
                title="🔍 Quest Search Results",
                description=f"Found {len(results)} quest(s)",
                color=discord.Color.blue()
            )
            
            for i, quest in enumerate(results[:10]):  # Limit to 10 results
                embed.add_field(
                    name=f"{quest.title} ({quest.rank})",
                    value=f"**ID:** {quest.quest_id}\n**Creator:** <@{quest.creator_id}>\n**Reward:** {quest.reward}",
                    inline=False
                )
            
            if len(results) > 10:
                embed.add_field(
                    name="📋 More Results",
                    value=f"Showing first 10 of {len(results)} results. Refine your search for fewer results.",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Search quests error: {e}")
            await interaction.followup.send("❌ Error searching quests. Please try again.")
    
    @app_commands.command(name="recommend_quests", description="Get AI-powered quest recommendations")
    @app_commands.describe(limit="Number of recommendations (max 10)")
    async def quest_recommendations(self, interaction: discord.Interaction, limit: Optional[int] = 5):
        """Get personalized quest recommendations"""
        await interaction.response.defer()
        
        try:
            if limit and (limit < 1 or limit > 10):
                limit = 5
            elif not limit:
                limit = 5
            
            recommendations = await self.bot.quest_recommendation_system.get_personalized_recommendations(
                interaction.user.id, interaction.guild_id, limit
            )
            
            if not recommendations:
                await interaction.followup.send("🎯 No recommendations available. Complete some quests first to get personalized suggestions!")
                return
            
            embed = discord.Embed(
                title="🎯 Quest Recommendations",
                description=f"Personalized suggestions for {interaction.user.display_name}",
                color=discord.Color.green()
            )
            
            for quest, reason, score in recommendations:
                confidence = "🔥" if score > 0.8 else "⭐" if score > 0.6 else "💡"
                embed.add_field(
                    name=f"{confidence} {quest.title} ({quest.rank})",
                    value=f"**Reason:** {reason}\n**ID:** {quest.quest_id}\n**Reward:** {quest.reward}",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Quest recommendations error: {e}")
            await interaction.followup.send("❌ Error getting recommendations. Please try again.")
    
    @app_commands.command(name="add_favorite", description="Bookmark a quest to your favorites")
    @app_commands.describe(
        quest_id="Quest ID to favorite",
        notes="Optional notes about why you favorited this quest"
    )
    async def favorite_quest(
        self, 
        interaction: discord.Interaction,
        quest_id: str,
        notes: Optional[str] = ""
    ):
        """Add a quest to favorites"""
        await interaction.response.defer()
        
        try:
            success = await self.bot.quest_favorites_system.add_favorite(
                quest_id, interaction.user.id, interaction.guild_id, notes or ""
            )
            
            if success:
                await interaction.followup.send(f"⭐ Quest `{quest_id}` added to your favorites!")
            else:
                await interaction.followup.send(f"❌ Could not favorite quest `{quest_id}`. Make sure the quest exists.")
                
        except Exception as e:
            logger.error(f"Favorite quest error: {e}")
            await interaction.followup.send("❌ Error adding to favorites. Please try again.")
    
    @app_commands.command(name="show_favorites", description="View your bookmarked quests")
    async def my_favorites(self, interaction: discord.Interaction):
        """View your favorite quests"""
        await interaction.response.defer()
        
        try:
            favorites = await self.bot.quest_favorites_system.get_user_favorites(
                interaction.user.id, interaction.guild_id
            )
            
            if not favorites:
                await interaction.followup.send("⭐ You haven't favorited any quests yet. Use `/favorite_quest` to start!")
                return
            
            embed = discord.Embed(
                title="⭐ Your Favorite Quests",
                description=f"{len(favorites)} favorited quest(s)",
                color=discord.Color.gold()
            )
            
            for fav in favorites[:10]:  # Limit to 10
                quest = await self.bot.quest_manager.get_quest(fav['quest_id'])
                if quest:
                    notes_text = f"\n**Notes:** {fav['notes']}" if fav['notes'] else ""
                    embed.add_field(
                        name=f"{quest.title} ({quest.rank})",
                        value=f"**ID:** {quest.quest_id}\n**Reward:** {quest.reward}{notes_text}",
                        inline=False
                    )
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            logger.error(f"My favorites error: {e}")
            await interaction.followup.send("❌ Error getting favorites. Please try again.")
    
    @app_commands.command(name="reminder_settings", description="Configure quest reminder notifications")
    @app_commands.describe(
        enabled="Enable or disable quest reminders",
        first_reminder_hours="Hours after accepting before first reminder",
        final_reminder_hours="Hours after accepting before final reminder"
    )
    async def quest_reminders(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        first_reminder_hours: Optional[int] = None,
        final_reminder_hours: Optional[int] = None
    ):
        """Manage quest reminder preferences"""
        await interaction.response.defer()
        
        try:
            if enabled is not None or first_reminder_hours or final_reminder_hours:
                # Update preferences
                await self.bot.quest_reminder_system.update_user_preferences(
                    interaction.user.id, interaction.guild_id,
                    enabled=enabled,
                    first_reminder_hours=first_reminder_hours,
                    final_reminder_hours=final_reminder_hours
                )
                await interaction.followup.send("✅ Quest reminder preferences updated!")
            else:
                # Show current preferences
                prefs = await self.bot.quest_reminder_system._get_user_reminder_preferences(
                    interaction.user.id, interaction.guild_id
                )
                
                embed = discord.Embed(
                    title="⏰ Your Quest Reminder Settings",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Enabled", value="✅ Yes" if prefs['enabled'] else "❌ No", inline=True)
                embed.add_field(name="First Reminder", value=f"{prefs['first_reminder_hours']} hours", inline=True)
                embed.add_field(name="Final Reminder", value=f"{prefs['final_reminder_hours']} hours", inline=True)
                
                await interaction.followup.send(embed=embed)
                
        except Exception as e:
            logger.error(f"Quest reminders error: {e}")
            await interaction.followup.send("❌ Error managing reminders. Please try again.")
    


async def setup(bot):
    await bot.add_cog(EnhancedQuestCommands(bot))