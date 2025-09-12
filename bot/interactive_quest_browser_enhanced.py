import discord
import asyncio
import math
import logging
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

class EnhancedQuestBrowser(discord.ui.View):
    """Enhanced interactive quest browser with advanced filtering and features"""
    
    def __init__(self, bot, user_id: int, guild_id: int):
        super().__init__(timeout=600)  # 10 minute timeout
        self.bot = bot
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = 0
        self.quests_per_page = 5
        self.filters = {
            'rank': None,
            'category': None,
            'has_prerequisites': False,
            'completed_only': False,
            'available_only': True
        }
        self.quests = []
        self.max_pages = 1
        
        # Initialize with available quests
        asyncio.create_task(self._load_quests())
    
    async def _load_quests(self):
        """Load quests based on current filters"""
        try:
            if not hasattr(self.bot, 'quest_manager'):
                return
                
            # Get base quests
            if self.filters['completed_only']:
                # Get completed quests for this user
                async with self.bot.database.pool.acquire() as conn:
                    quest_rows = await conn.fetch('''
                        SELECT q.*, qp.completed_at, qp.status
                        FROM quests q
                        JOIN quest_progress qp ON q.quest_id = qp.quest_id
                        WHERE qp.user_id = $1 AND q.guild_id = $2 AND qp.status = 'approved'
                        ORDER BY qp.completed_at DESC
                    ''', self.user_id, self.guild_id)
            else:
                # Get available quests
                quest_rows = await self.bot.quest_manager.get_available_quests(self.guild_id)
            
            # Apply filters
            filtered_quests = []
            for quest in quest_rows:
                # Rank filter
                if self.filters['rank'] and quest.rank != self.filters['rank']:
                    continue
                
                # Category filter
                if self.filters['category'] and quest.category != self.filters['category']:
                    continue
                
                # Prerequisites filter
                if self.filters['has_prerequisites']:
                    if hasattr(self.bot, 'advanced_quest_features'):
                        has_prereqs = await self._check_has_prerequisites(quest.quest_id)
                        if not has_prereqs:
                            continue
                
                # Available only filter (check if user can accept)
                if self.filters['available_only'] and not self.filters['completed_only']:
                    can_accept = await self._can_user_accept(quest.quest_id)
                    if not can_accept:
                        continue
                
                filtered_quests.append(quest)
            
            self.quests = filtered_quests
            self.max_pages = max(1, math.ceil(len(self.quests) / self.quests_per_page))
            self.current_page = min(self.current_page, self.max_pages - 1)
            
            await self._update_display()
            
        except Exception as e:
            logger.error(f"❌ Error loading quests: {e}")
    
    async def _check_has_prerequisites(self, quest_id: str) -> bool:
        """Check if quest has prerequisites"""
        try:
            async with self.bot.database.pool.acquire() as conn:
                prereq_count = await conn.fetchval('''
                    SELECT COUNT(*) FROM quest_dependencies 
                    WHERE quest_id = $1
                ''', quest_id)
                return prereq_count > 0
        except:
            return False
    
    async def _can_user_accept(self, quest_id: str) -> bool:
        """Check if user can accept the quest (including prerequisites)"""
        try:
            # Check if already accepted/completed
            async with self.bot.database.pool.acquire() as conn:
                existing = await conn.fetchval('''
                    SELECT COUNT(*) FROM quest_progress 
                    WHERE user_id = $1 AND quest_id = $2 
                    AND status IN ('accepted', 'completed', 'approved')
                ''', self.user_id, quest_id)
                
                if existing > 0:
                    return False
            
            # Check prerequisites if advanced features are available
            if hasattr(self.bot, 'advanced_quest_features'):
                return await self.bot.advanced_quest_features.check_quest_prerequisites(
                    self.user_id, quest_id, self.guild_id
                )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Error checking quest acceptance: {e}")
            return False
    
    async def _update_display(self):
        """Update the display with current quests and buttons"""
        try:
            # Clear existing items
            self.clear_items()
            
            # Add filter controls
            await self._add_filter_controls()
            
            # Add navigation buttons
            await self._add_navigation_buttons()
            
            # Add quest action buttons
            await self._add_quest_buttons()
            
        except Exception as e:
            logger.error(f"❌ Error updating display: {e}")
    
    async def _add_filter_controls(self):
        """Add filter control buttons"""
        # Rank filter dropdown
        rank_select = discord.ui.Select(
            placeholder="Filter by Rank",
            options=[
                discord.SelectOption(label="All Ranks", value="all"),
                discord.SelectOption(label="Easy", value="Easy"),
                discord.SelectOption(label="Normal", value="Normal"),
                discord.SelectOption(label="Medium", value="Medium"),
                discord.SelectOption(label="Hard", value="Hard"),
                discord.SelectOption(label="Impossible", value="Impossible")
            ],
            row=0
        )
        rank_select.callback = self._rank_filter_callback
        self.add_item(rank_select)
        
        # Category filter dropdown
        categories = await self._get_available_categories()
        if categories:
            category_options = [discord.SelectOption(label="All Categories", value="all")]
            category_options.extend([
                discord.SelectOption(label=cat.title(), value=cat) for cat in categories[:23]
            ])
            
            category_select = discord.ui.Select(
                placeholder="Filter by Category",
                options=category_options,
                row=0
            )
            category_select.callback = self._category_filter_callback
            self.add_item(category_select)
        
        # Toggle buttons
        if not self.filters['completed_only']:
            prereq_button = discord.ui.Button(
                label="With Prerequisites" if self.filters['has_prerequisites'] else "All Quests",
                style=discord.ButtonStyle.secondary if not self.filters['has_prerequisites'] else discord.ButtonStyle.primary,
                emoji="🔗",
                row=1
            )
            prereq_button.callback = self._toggle_prerequisites
            self.add_item(prereq_button)
        
        view_mode_button = discord.ui.Button(
            label="Completed" if self.filters['completed_only'] else "Available",
            style=discord.ButtonStyle.success if not self.filters['completed_only'] else discord.ButtonStyle.secondary,
            emoji="✅" if self.filters['completed_only'] else "📋",
            row=1
        )
        view_mode_button.callback = self._toggle_view_mode
        self.add_item(view_mode_button)
    
    async def _add_navigation_buttons(self):
        """Add navigation buttons"""
        prev_button = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.grey,
            emoji="⬅️",
            disabled=self.current_page <= 0,
            row=2
        )
        prev_button.callback = self._previous_page
        self.add_item(prev_button)
        
        next_button = discord.ui.Button(
            label="Next", 
            style=discord.ButtonStyle.grey,
            emoji="➡️",
            disabled=self.current_page >= self.max_pages - 1,
            row=2
        )
        next_button.callback = self._next_page
        self.add_item(next_button)
        
        # Page info button
        page_button = discord.ui.Button(
            label=f"Page {self.current_page + 1}/{self.max_pages}",
            style=discord.ButtonStyle.blurple,
            disabled=True,
            row=2
        )
        self.add_item(page_button)
    
    async def _add_quest_buttons(self):
        """Add quest action buttons for current page"""
        start_idx = self.current_page * self.quests_per_page
        end_idx = min(start_idx + self.quests_per_page, len(self.quests))
        current_quests = self.quests[start_idx:end_idx]
        
        for i, quest in enumerate(current_quests):
            if not self.filters['completed_only']:
                # Accept button
                accept_button = discord.ui.Button(
                    label=f"Accept #{quest.quest_id[:6]}",
                    style=discord.ButtonStyle.success,
                    emoji="✅",
                    row=3 + (i // 2)
                )
                accept_button.callback = self._create_accept_callback(quest)
                self.add_item(accept_button)
            
            # Info button
            info_button = discord.ui.Button(
                label=f"Info #{quest.quest_id[:6]}",
                style=discord.ButtonStyle.secondary,
                emoji="ℹ️",
                row=3 + (i // 2)
            )
            info_button.callback = self._create_info_callback(quest)
            self.add_item(info_button)
    
    async def _get_available_categories(self) -> List[str]:
        """Get list of available quest categories"""
        try:
            async with self.bot.database.pool.acquire() as conn:
                categories = await conn.fetch('''
                    SELECT DISTINCT category FROM quests 
                    WHERE guild_id = $1 AND category IS NOT NULL AND category != ''
                    ORDER BY category
                ''', self.guild_id)
                return [cat['category'] for cat in categories]
        except:
            return []
    
    def _create_accept_callback(self, quest):
        """Create callback for accept button"""
        async def callback(interaction):
            try:
                await interaction.response.defer()
                
                # Get user roles
                user = interaction.user
                user_role_ids = [role.id for role in user.roles]
                
                # Try to accept the quest
                progress, error = await self.bot.quest_manager.accept_quest(
                    quest.quest_id, user.id, user_role_ids, interaction.channel.id
                )
                
                if error:
                    embed = discord.Embed(
                        title="Quest Acceptance Failed",
                        description=error,
                        color=discord.Color.red()
                    )
                else:
                    embed = discord.Embed(
                        title="Quest Accepted!",
                        description=f"Successfully accepted: **{quest.title}**",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="Quest ID",
                        value=f"`{quest.quest_id}`",
                        inline=True
                    )
                    embed.add_field(
                        name="Next Steps",
                        value="Check your progress with `/my_quests`",
                        inline=True
                    )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                # Refresh the browser
                await self._load_quests()
                
            except Exception as e:
                logger.error(f"❌ Error in accept callback: {e}")
        
        return callback
    
    def _create_info_callback(self, quest):
        """Create callback for info button"""
        async def callback(interaction):
            try:
                embed = discord.Embed(
                    title=f"Quest: {quest.title}",
                    description=quest.description[:1024],
                    color=discord.Color.blue()
                )
                
                embed.add_field(name="ID", value=f"`{quest.quest_id}`", inline=True)
                embed.add_field(name="Rank", value=quest.rank, inline=True)
                embed.add_field(name="Category", value=quest.category or "General", inline=True)
                
                if quest.requirements:
                    embed.add_field(
                        name="Requirements",
                        value=quest.requirements[:512],
                        inline=False
                    )
                
                if quest.reward:
                    embed.add_field(
                        name="Reward",
                        value=quest.reward[:512],
                        inline=False
                    )
                
                # Check prerequisites
                if hasattr(self.bot, 'advanced_quest_features'):
                    missing_prereqs = await self.bot.advanced_quest_features.get_missing_prerequisites(
                        self.user_id, quest.quest_id, self.guild_id
                    )
                    if missing_prereqs:
                        embed.add_field(
                            name="Missing Prerequisites",
                            value="\n".join(missing_prereqs[:5]),
                            inline=False
                        )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"❌ Error in info callback: {e}")
        
        return callback
    
    # Filter callbacks
    async def _rank_filter_callback(self, interaction):
        """Handle rank filter selection"""
        try:
            await interaction.response.defer()
            self.filters['rank'] = None if interaction.data['values'][0] == 'all' else interaction.data['values'][0]
            await self._load_quests()
        except Exception as e:
            logger.error(f"❌ Error in rank filter: {e}")
    
    async def _category_filter_callback(self, interaction):
        """Handle category filter selection"""
        try:
            await interaction.response.defer()
            self.filters['category'] = None if interaction.data['values'][0] == 'all' else interaction.data['values'][0]
            await self._load_quests()
        except Exception as e:
            logger.error(f"❌ Error in category filter: {e}")
    
    async def _toggle_prerequisites(self, interaction):
        """Toggle prerequisites filter"""
        try:
            await interaction.response.defer()
            self.filters['has_prerequisites'] = not self.filters['has_prerequisites']
            await self._load_quests()
        except Exception as e:
            logger.error(f"❌ Error toggling prerequisites: {e}")
    
    async def _toggle_view_mode(self, interaction):
        """Toggle between available and completed quests"""
        try:
            await interaction.response.defer()
            self.filters['completed_only'] = not self.filters['completed_only']
            self.filters['available_only'] = not self.filters['completed_only']
            await self._load_quests()
        except Exception as e:
            logger.error(f"❌ Error toggling view mode: {e}")
    
    # Navigation callbacks
    async def _previous_page(self, interaction):
        """Go to previous page"""
        try:
            await interaction.response.defer()
            if self.current_page > 0:
                self.current_page -= 1
                await self._update_display()
        except Exception as e:
            logger.error(f"❌ Error in previous page: {e}")
    
    async def _next_page(self, interaction):
        """Go to next page"""
        try:
            await interaction.response.defer()
            if self.current_page < self.max_pages - 1:
                self.current_page += 1
                await self._update_display()
        except Exception as e:
            logger.error(f"❌ Error in next page: {e}")
    
    async def get_current_embed(self) -> discord.Embed:
        """Get the embed for current page"""
        try:
            start_idx = self.current_page * self.quests_per_page
            end_idx = min(start_idx + self.quests_per_page, len(self.quests))
            current_quests = self.quests[start_idx:end_idx]
            
            title = "Available Quests" if not self.filters['completed_only'] else "Completed Quests"
            embed = discord.Embed(
                title=f"🎯 {title} (Page {self.current_page + 1}/{self.max_pages})",
                color=discord.Color.green() if not self.filters['completed_only'] else discord.Color.blue()
            )
            
            if not current_quests:
                embed.description = "No quests found matching your filters."
                return embed
            
            for i, quest in enumerate(current_quests):
                quest_value = f"**Rank:** {quest.rank}\n**Category:** {quest.category or 'General'}"
                
                if hasattr(quest, 'reward') and quest.reward:
                    quest_value += f"\n**Reward:** {quest.reward[:100]}..."
                
                if self.filters['completed_only'] and hasattr(quest, 'completed_at'):
                    quest_value += f"\n**Completed:** {quest.completed_at.strftime('%Y-%m-%d')}"
                
                embed.add_field(
                    name=f"{i+1}. {quest.title} (`{quest.quest_id[:8]}`)",
                    value=quest_value,
                    inline=False
                )
            
            # Add filter info
            filter_info = []
            if self.filters['rank']:
                filter_info.append(f"Rank: {self.filters['rank']}")
            if self.filters['category']:
                filter_info.append(f"Category: {self.filters['category']}")
            if self.filters['has_prerequisites']:
                filter_info.append("With Prerequisites")
            
            if filter_info:
                embed.set_footer(text=f"Filters: {', '.join(filter_info)}")
            
            return embed
            
        except Exception as e:
            logger.error(f"❌ Error creating embed: {e}")
            embed = discord.Embed(
                title="Error",
                description="Failed to load quest information.",
                color=discord.Color.red()
            )
            return embed