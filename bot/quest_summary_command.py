import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

class QuestSummaryCommand(commands.Cog):
    def __init__(self, bot, database):
        self.bot = bot
        self.database = database

    @app_commands.command(name="quest_summary", description="View quest completion summary for yourself or another user")
    @app_commands.describe(
        user="User to check quest summary for (leave blank for yourself)"
    )
    async def quest_summary(self, interaction: discord.Interaction, user: discord.Member = None):
        """Show detailed quest completion summary by rank and category"""
        target_user = user or interaction.user
        
        try:
            async with self.database.pool.acquire() as conn:
                # Get quest completion data grouped by rank and category
                quest_data = await conn.fetch('''
                    SELECT 
                        q.rank,
                        q.category,
                        COUNT(*) as completed_count,
                        STRING_AGG(q.title, ', ' ORDER BY qp.completed_at) as quest_titles
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                    GROUP BY q.rank, q.category
                    ORDER BY 
                        CASE q.rank 
                            WHEN 'Easy' THEN 1 
                            WHEN 'Normal' THEN 2 
                            WHEN 'Medium' THEN 3 
                            WHEN 'Hard' THEN 4 
                            WHEN 'Impossible' THEN 5 
                            ELSE 6 
                        END,
                        q.category
                ''', target_user.id, interaction.guild_id)
                
                # Get total counts by rank
                rank_totals = await conn.fetch('''
                    SELECT 
                        q.rank,
                        COUNT(*) as total_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                    WHERE qp.user_id = $1 AND qp.guild_id = $2 AND qp.status = 'approved'
                    GROUP BY q.rank
                    ORDER BY 
                        CASE q.rank 
                            WHEN 'Easy' THEN 1 
                            WHEN 'Normal' THEN 2 
                            WHEN 'Medium' THEN 3 
                            WHEN 'Hard' THEN 4 
                            WHEN 'Impossible' THEN 5 
                            ELSE 6 
                        END
                ''', target_user.id, interaction.guild_id)
                
                # Get total points
                total_points = await conn.fetchval('''
                    SELECT COALESCE(points, 0) FROM leaderboard 
                    WHERE user_id = $1 AND guild_id = $2
                ''', target_user.id, interaction.guild_id) or 0

        except Exception as e:
            logger.error(f"Error fetching quest summary: {e}")
            await interaction.response.send_message("❌ Error fetching quest data.", ephemeral=True)
            return

        if not quest_data and not rank_totals:
            await interaction.response.send_message(
                f"📊 **{target_user.display_name}** has not completed any quests yet.",
                ephemeral=True
            )
            return

        # Build the summary embed
        embed = discord.Embed(
            title=f"📊 Quest Summary - {target_user.display_name}",
            color=discord.Color.blue(),
            description=f"**Total Points:** {total_points:,}"
        )

        # Add rank totals at the top
        if rank_totals:
            rank_summary = []
            for rank_data in rank_totals:
                rank = rank_data['rank']
                count = rank_data['total_count']
                
                # Add appropriate emoji for each rank
                rank_emoji = {
                    'Easy': '🟢',
                    'Normal': '🟡', 
                    'Medium': '🟠',
                    'Hard': '🔴',
                    'Impossible': '⚫'
                }.get(rank, '⚪')
                
                rank_summary.append(f"{rank_emoji} **{rank}:** {count}")
            
            embed.add_field(
                name="📈 Completion by Rank",
                value="\n".join(rank_summary),
                inline=True
            )

        # Group data by rank for detailed breakdown
        rank_groups = {}
        for row in quest_data:
            rank = row['rank']
            if rank not in rank_groups:
                rank_groups[rank] = []
            rank_groups[rank].append(row)

        # Add detailed breakdown by rank and category
        rank_order = ['Easy', 'Normal', 'Medium', 'Hard', 'Impossible']
        for rank in rank_order:
            if rank in rank_groups:
                category_info = []
                for row in rank_groups[rank]:
                    category = row['category'] or 'General'
                    count = row['completed_count']
                    
                    # Truncate quest titles if too long
                    titles = row['quest_titles']
                    if len(titles) > 100:
                        titles = titles[:97] + "..."
                    
                    category_info.append(f"**{category}:** {count}\n*{titles}*")
                
                rank_emoji_map = {
                    'Easy': '🟢',
                    'Normal': '🟡', 
                    'Medium': '🟠',
                    'Hard': '🔴',
                    'Impossible': '⚫'
                }
                
                embed.add_field(
                    name=f"{rank_emoji_map.get(rank, '⚪')} {rank} Quests Detail",
                    value="\n\n".join(category_info),
                    inline=False
                )

        # Add footer with useful info
        embed.set_footer(text="Use /check_rank_requirements to see what you need for your next rank!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="server_quest_stats", description="View server-wide quest completion statistics (Admin only)")
    async def server_quest_stats(self, interaction: discord.Interaction):
        """Show server-wide quest completion statistics"""
        
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ This command requires administrator permissions.", ephemeral=True)
            return
        
        try:
            async with self.database.pool.acquire() as conn:
                # Get overall stats
                total_completed = await conn.fetchval('''
                    SELECT COUNT(*) FROM quest_progress 
                    WHERE guild_id = $1 AND status = 'approved'
                ''', interaction.guild_id)
                
                total_users = await conn.fetchval('''
                    SELECT COUNT(DISTINCT user_id) FROM quest_progress 
                    WHERE guild_id = $1 AND status = 'approved'
                ''', interaction.guild_id)
                
                # Get stats by rank
                rank_stats = await conn.fetch('''
                    SELECT 
                        q.rank,
                        COUNT(*) as completion_count,
                        COUNT(DISTINCT qp.user_id) as unique_users
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                    WHERE qp.guild_id = $1 AND qp.status = 'approved'
                    GROUP BY q.rank
                    ORDER BY 
                        CASE q.rank 
                            WHEN 'Easy' THEN 1 
                            WHEN 'Normal' THEN 2 
                            WHEN 'Medium' THEN 3 
                            WHEN 'Hard' THEN 4 
                            WHEN 'Impossible' THEN 5 
                            ELSE 6 
                        END
                ''', interaction.guild_id)
                
                # Get top performers
                top_performers = await conn.fetch('''
                    SELECT 
                        user_id,
                        COUNT(*) as quest_count
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id AND qp.guild_id = q.guild_id
                    WHERE qp.guild_id = $1 AND qp.status = 'approved'
                    GROUP BY user_id
                    ORDER BY quest_count DESC
                    LIMIT 10
                ''', interaction.guild_id)

        except Exception as e:
            logger.error(f"Error fetching server quest stats: {e}")
            await interaction.response.send_message("❌ Error fetching server statistics.", ephemeral=True)
            return

        # Build the statistics embed
        embed = discord.Embed(
            title="📊 Server Quest Statistics",
            color=discord.Color.gold(),
            description=f"**Total Completed Quests:** {total_completed:,}\n**Active Quest Users:** {total_users:,}"
        )

        # Add rank breakdown
        if rank_stats:
            rank_info = []
            for row in rank_stats:
                rank = row['rank']
                count = row['completion_count']
                users = row['unique_users']
                
                rank_emoji = {
                    'Easy': '🟢',
                    'Normal': '🟡', 
                    'Medium': '🟠',
                    'Hard': '🔴',
                    'Impossible': '⚫'
                }.get(rank, '⚪')
                
                rank_info.append(f"{rank_emoji} **{rank}:** {count:,} completions ({users} users)")
            
            embed.add_field(
                name="📈 Completions by Rank",
                value="\n".join(rank_info),
                inline=False
            )

        # Add top performers
        if top_performers:
            performer_info = []
            for i, row in enumerate(top_performers, 1):
                try:
                    user = self.bot.get_user(row['user_id'])
                    name = user.display_name if user else f"User {row['user_id']}"
                    count = row['quest_count']
                    
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    performer_info.append(f"{medal} **{name}:** {count} quests")
                except:
                    continue
            
            if performer_info:
                embed.add_field(
                    name="🏆 Top Quest Completers",
                    value="\n".join(performer_info),
                    inline=False
                )

        embed.set_footer(text="This shows all quest completions since the bot started tracking")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

