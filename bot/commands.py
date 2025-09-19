import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List
import typing
from datetime import datetime
import logging
import asyncio
import math

from bot.models import QuestRank, QuestCategory, QuestStatus, ProgressStatus
from bot.quest_manager import QuestManager
from bot.config import ChannelConfig
from bot.user_stats import UserStatsManager
from bot.permissions import has_quest_creation_permission, can_manage_quest, user_has_required_roles
from bot.utils import (
    create_leaderboard_embed, create_user_stats_embed, create_success_embed,
    create_error_embed, create_info_embed, create_quest_embed, Colors, 
    get_total_guild_points, get_rank_title_by_points, create_promotion_embed, 
    get_rank_color, truncate_text, get_quest_rank_color, create_team_quest_embed,
    create_quest_list_embed, create_progress_bar
)

from bot.team_quest_manager import TeamQuestManager
from bot.bounty_manager import BountyManager

logger = logging.getLogger(__name__)

# Global list to track active leaderboard views
active_leaderboard_views = []

class InteractiveQuestBrowser(discord.ui.View):
    """Interactive quest browser with pagination and quick actions"""
    
    def __init__(self, quests, quest_manager, team_quest_manager, user_id, guild_id, 
                 rank_filter=None, category_filter=None, show_all=False):
        super().__init__(timeout=300)  # 5 minute timeout
        self.quests = quests
        self.quest_manager = quest_manager
        self.team_quest_manager = team_quest_manager
        self.user_id = user_id
        self.guild_id = guild_id
        self.rank_filter = rank_filter
        self.category_filter = category_filter
        self.show_all = show_all
        self.current_page = 0
        self.quests_per_page = 3
        self.max_pages = math.ceil(len(quests) / self.quests_per_page) if quests else 1
        
        # Update button states
        self.update_buttons()
    
    def update_buttons(self):
        """Update button states based on current page"""
        # Navigation buttons
        self.previous_button.disabled = self.current_page <= 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1
        
        # Clear existing quest action buttons
        for item in self.children[:]:
            if hasattr(item, 'quest_id'):
                self.remove_item(item)
        
        # Add quest action buttons for current page
        start_idx = self.current_page * self.quests_per_page
        end_idx = min(start_idx + self.quests_per_page, len(self.quests))
        current_quests = self.quests[start_idx:end_idx]
        
        for i, quest in enumerate(current_quests):
            # Create accept button for each quest
            button = discord.ui.Button(
                label=f"Accept {quest.title[:20]}{'...' if len(quest.title) > 20 else ''}",
                style=discord.ButtonStyle.success,
                emoji="✅",
                row=2 + (i // 2)  # Arrange in rows
            )
            button.quest_id = quest.quest_id
            button.callback = self.create_accept_callback(quest.quest_id, quest.title)
            self.add_item(button)
            
            # Create info button for each quest
            info_button = discord.ui.Button(
                label=f"Info",
                style=discord.ButtonStyle.secondary,
                emoji="ℹ️",
                row=2 + (i // 2)  # Same row as accept button
            )
            info_button.quest_id = quest.quest_id
            info_button.callback = self.create_info_callback(quest.quest_id)
            self.add_item(info_button)
    
    def create_accept_callback(self, quest_id, quest_title):
        """Create callback for accept button"""
        async def accept_callback(interaction):
            try:
                await interaction.response.defer(ephemeral=True)
                
                # Get user roles for quest acceptance
                user = interaction.user
                user_role_ids = [role.id for role in user.roles]
                
                # Try to accept the quest
                progress, error = await self.quest_manager.accept_quest(
                    quest_id, user.id, user_role_ids, interaction.channel.id
                )
                
                if error:
                    embed = create_error_embed("Quest Acceptance Failed", error)
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    embed = create_success_embed(
                        "Quest Accepted!",
                        f"Successfully accepted: **{quest_title}**",
                        f"Quest ID: `{quest_id}`\nCheck your progress with `/my_quests`"
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    logger.info(f"✅ {user.display_name} accepted quest {quest_id} via interactive browser")
                    
            except Exception as e:
                logger.error(f"❌ Error in accept callback: {e}")
                embed = create_error_embed("Error", "Failed to accept quest. Please try again.")
                await interaction.followup.send(embed=embed, ephemeral=True)
        
        return accept_callback
    
    def create_info_callback(self, quest_id):
        """Create callback for info button"""
        async def info_callback(interaction):
            try:
                await interaction.response.defer(ephemeral=True)
                
                # Get quest details
                quest = await self.quest_manager.get_quest(quest_id)
                if not quest:
                    embed = create_error_embed("Quest Not Found", "Quest no longer exists.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                # Check if this is a team quest
                team_info = None
                if self.team_quest_manager:
                    team_info = await self.team_quest_manager.get_team_status(quest_id)
                
                # Create detailed quest embed
                embed = create_quest_embed(quest, team_info=team_info)
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"❌ Error in info callback: {e}")
                embed = create_error_embed("Error", "Failed to get quest information.")
                await interaction.followup.send(embed=embed, ephemeral=True)
        
        return info_callback
    
    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=0)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh quest list"""
        try:
            await interaction.response.defer()
            
            # Refresh quest list with same filters
            if self.show_all:
                self.quests = await self.quest_manager.get_guild_quests(self.guild_id)
            else:
                self.quests = await self.quest_manager.get_available_quests(self.guild_id)
            
            # Apply filters
            if self.rank_filter:
                self.quests = [q for q in self.quests if q.rank == self.rank_filter]
            if self.category_filter:
                self.quests = [q for q in self.quests if q.category == self.category_filter]
            
            # Update pagination
            self.max_pages = math.ceil(len(self.quests) / self.quests_per_page) if self.quests else 1
            if self.current_page >= self.max_pages:
                self.current_page = max(0, self.max_pages - 1)
            
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.edit_original_response(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"❌ Error refreshing quest browser: {e}")
    
    @discord.ui.button(label="📋 My Quests", style=discord.ButtonStyle.secondary, row=1)
    async def my_quests_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show user's quests"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            user_quests = await self.quest_manager.get_user_quests(self.user_id, self.guild_id)
            
            if not user_quests:
                embed = create_info_embed(
                    "No Quest Activity",
                    "You haven't accepted any quests yet.",
                    "Accept some quests from the list above to get started!"
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return
            
            # Create a quick summary
            active_quests = [q for q in user_quests if q.status == 'accepted']
            completed_quests = [q for q in user_quests if q.status == 'approved']
            
            embed = create_info_embed(
                "Your Quest Summary",
                f"📊 **Active**: {len(active_quests)} quests\n✅ **Completed**: {len(completed_quests)} quests",
                "Use `/my_quests` for detailed progress view"
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"❌ Error in my_quests callback: {e}")
    
    async def create_page_embed(self, guild):
        """Create embed for current page"""
        embed = discord.Embed(
            title=f"Quest Board - {guild.name}",
            description=f"**{len(self.quests)}** quest{'s' if len(self.quests) != 1 else ''} found • Page {self.current_page + 1}/{self.max_pages}",
            color=Colors.SECONDARY
        )
        
        # Add quests for current page
        start_idx = self.current_page * self.quests_per_page
        end_idx = min(start_idx + self.quests_per_page, len(self.quests))
        current_quests = self.quests[start_idx:end_idx]
        
        for quest in current_quests:
            status_text = quest.status.title()
            
            # Check if this is a team quest
            team_status = None
            if self.team_quest_manager:
                team_status = await self.team_quest_manager.get_team_status(quest.quest_id)
            
            quest_info = f"**Difficulty:** {quest.rank.title()}\n**Category:** {quest.category.title()}\n**Status:** {status_text}"
            
            # Add team information
            if team_status:
                quest_info += f"\n**Type:** Team Quest ({team_status.team_size_required} members)"
            else:
                quest_info += f"\n**Type:** Solo Quest"
            
            if quest.reward:
                reward_preview = quest.reward[:40] + '...' if len(quest.reward) > 40 else quest.reward
                quest_info += f"\n**Reward:** {reward_preview}"
            
            embed.add_field(
                name=f"■ {quest.title}",
                value=f"```yaml\nID: {quest.quest_id}\n```{quest_info}",
                inline=True
            )
        
        # Add filter info
        filter_info = []
        if self.rank_filter:
            filter_info.append(f"**Difficulty:** {self.rank_filter.title()}")
        if self.category_filter:
            filter_info.append(f"**Category:** {self.category_filter.title()}")
        if self.show_all:
            filter_info.append("**Scope:** All Quests")
        else:
            filter_info.append("**Scope:** Available Only")
        
        if filter_info:
            embed.add_field(
                name="■ Active Filters",
                value=" • ".join(filter_info),
                inline=False
            )
        
        embed.set_footer(text="Use the buttons below to navigate and interact with quests")
        return embed
    
    async def on_timeout(self):
        """Called when the view times out"""
        # Disable all buttons
        for item in self.children:
            item.disabled = True

class InteractiveMyQuestsView(discord.ui.View):
    """Interactive view for my_quests command with quest management actions"""
    
    def __init__(self, user_quests, quest_manager, user_id, guild_id):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_quests = user_quests
        self.quest_manager = quest_manager
        self.user_id = user_id
        self.guild_id = guild_id
        self.current_page = 0
        self.quests_per_page = 3
        
        # Group quests by status
        self.status_groups = {}
        for progress in user_quests:
            status = progress.status
            if status not in self.status_groups:
                self.status_groups[status] = []
            self.status_groups[status].append(progress)
        
        # Get accepted quests for interactive buttons
        self.accepted_quests = self.status_groups.get('accepted', [])
        self.max_pages = math.ceil(len(self.accepted_quests) / self.quests_per_page) if self.accepted_quests else 1
        
        self.update_buttons()
    
    def update_buttons(self):
        """Update button states based on current quest selection"""
        # Clear existing quest action buttons
        for item in self.children[:]:
            if hasattr(item, 'quest_id'):
                self.remove_item(item)
        
        # Navigation buttons state
        self.previous_button.disabled = self.current_page <= 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1
        
        # Add quest action buttons for current page of accepted quests
        if self.accepted_quests:
            start_idx = self.current_page * self.quests_per_page
            end_idx = min(start_idx + self.quests_per_page, len(self.accepted_quests))
            current_quests = self.accepted_quests[start_idx:end_idx]
            
            for i, progress in enumerate(current_quests):
                # Details button for each quest showing quest ID
                details_button = discord.ui.Button(
                    label=f"Info | {progress.quest_id}",
                    style=discord.ButtonStyle.secondary,
                    emoji="ℹ️",
                    row=2 + (i // 2)  # Two buttons per row
                )
                details_button.quest_id = progress.quest_id
                details_button.callback = self.create_details_callback(progress.quest_id)
                self.add_item(details_button)
    
    
    
    def create_details_callback(self, quest_id):
        """Create callback for details button"""
        async def details_callback(interaction):
            try:
                await interaction.response.defer(ephemeral=True)
                
                quest = await self.quest_manager.get_quest(quest_id)
                if not quest:
                    embed = create_error_embed("Quest Not Found", "This quest no longer exists.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    return
                
                embed = create_quest_embed(quest)
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"❌ Error showing quest details: {e}")
                embed = create_error_embed("Error", "Failed to get quest details.")
                await interaction.followup.send(embed=embed, ephemeral=True)
        return details_callback
    
    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page of accepted quests"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.create_updated_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page of accepted quests"""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.create_updated_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh quest progress"""
        try:
            await interaction.response.defer()
            
            # Refresh quest data
            self.user_quests = await self.quest_manager.get_user_quests(self.user_id, self.guild_id)
            
            # Regroup by status
            self.status_groups = {}
            for progress in self.user_quests:
                status = progress.status
                if status not in self.status_groups:
                    self.status_groups[status] = []
                self.status_groups[status].append(progress)
            
            self.accepted_quests = self.status_groups.get('accepted', [])
            self.max_pages = math.ceil(len(self.accepted_quests) / self.quests_per_page) if self.accepted_quests else 1
            
            if self.current_page >= self.max_pages:
                self.current_page = max(0, self.max_pages - 1)
            
            self.update_buttons()
            embed = await self.create_updated_embed(interaction.guild)
            await interaction.edit_original_response(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"❌ Error refreshing my quests: {e}")
    
    async def create_updated_embed(self, guild):
        """Create updated embed with current quest data"""
        embed = create_success_embed(
            f"PERSONAL QUEST DOSSIER • {guild.get_member(self.user_id).display_name.upper()}",
            f"Disciple: {guild.get_member(self.user_id).display_name}\nGuild: {guild.name}"
        )
        
        # Display accepted missions 
        if 'accepted' in self.status_groups:
            accepted_quests = self.status_groups['accepted']
            quest_list = []
            
            for progress in accepted_quests[:10]:  # Show up to 10 quests
                quest = await self.quest_manager.get_quest(progress.quest_id)
                if quest:
                    quest_list.append(f"▸ **{quest.title}**\n   📝 Quest ID: `{quest.quest_id}`")
            
            embed.add_field(
                name="━━━━━━━━━ ACCEPTED MISSIONS ━━━━━━━━━",
                value=f"Total: {len(accepted_quests)} missions\n\n" + "\n\n".join(quest_list) if quest_list else "No active missions",
                inline=False
            )

        # Display approved missions 
        if 'approved' in self.status_groups:
            approved_quests = self.status_groups['approved']
            quest_list = []
            
            for progress in approved_quests[:10]:  # Show up to 10 quests
                quest = await self.quest_manager.get_quest(progress.quest_id)
                if quest:
                    quest_list.append(f"▸ **{quest.title}**\n   📝 Quest ID: `{quest.quest_id}`")
            
            embed.add_field(
                name="━━━━━━━━━ APPROVED MISSIONS ━━━━━━━━━",
                value=f"Total: {len(approved_quests)} missions\n\n" + "\n\n".join(quest_list) if quest_list else "No completed missions",
                inline=False
            )
        
        # Add interactive help
        if self.accepted_quests:
            embed.add_field(
                name="━━━━━━━━━ QUEST ACTIONS ━━━━━━━━━",
                value="Use the info buttons below to view detailed quest information\nUse `/submit_quest` command to submit proof when ready",
                inline=False
            )
        
        return embed

class QuestSubmissionModal(discord.ui.Modal):
    """Modal for quest submission"""
    
    def __init__(self, quest_id, quest_manager):
        super().__init__(title=f"Submit Quest: {quest_id}")
        self.quest_id = quest_id
        self.quest_manager = quest_manager
        
        self.proof_text = discord.ui.TextInput(
            label="Proof Description",
            placeholder="Describe how you completed this quest...",
            style=discord.TextStyle.long,
            max_length=2000,
            required=True
        )
        self.add_item(self.proof_text)
    
    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Submit the quest directly with text proof only
            progress = await self.quest_manager.complete_quest(
                self.quest_id,
                interaction.user.id,
                self.proof_text.value,
                []  # No images
            )
            
            if progress:
                quest = await self.quest_manager.get_quest(self.quest_id)
                quest_title = quest.title if quest else "Unknown Quest"
                
                embed = create_success_embed(
                    "Quest Submitted Successfully!",
                    f"Your proof for **{quest_title}** has been submitted for review.",
                    f"Quest ID: `{self.quest_id}`\nYour submission is now awaiting admin approval."
                )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
                # Send notification to approval channel
                approval_channel_id = await self.quest_manager.database.get_quest_approval_channel(interaction.guild.id)
                if approval_channel_id:
                    approval_channel = interaction.guild.get_channel(approval_channel_id)
                    if approval_channel:
                        approval_embed = discord.Embed(
                            title="QUEST SUBMISSION | PENDING APPROVAL",
                            color=Colors.WARNING,
                            timestamp=discord.utils.utcnow()
                        )
                        approval_embed.description = f"**{quest_title}** requires administrative review"
                        
                        # Quest details section
                        quest_rank = str(quest.rank).title() if quest and quest.rank else 'Unknown'
                        quest_details = f"**Quest ID:** `{self.quest_id}`\n**Title:** {quest_title}\n**Rank:** {quest_rank}"
                        approval_embed.add_field(
                            name="▬ QUEST DETAILS", 
                            value=quest_details, 
                            inline=True
                        )
                        
                        # User details section
                        user_details = f"**User:** {interaction.user.display_name}\n**User ID:** {interaction.user.id}\n**Mention:** {interaction.user.mention}"
                        approval_embed.add_field(
                            name="▬ USER DETAILS", 
                            value=user_details, 
                            inline=True
                        )
                        
                        # Proof section with text only
                        proof_text = self.proof_text.value[:1000] + "..." if len(self.proof_text.value) > 1000 else self.proof_text.value
                        approval_embed.add_field(
                            name="▬ PROOF DESCRIPTION", 
                            value=f"```{proof_text}```", 
                            inline=False
                        )
                        
                        # Add approval/rejection buttons
                        view = QuestApprovalView(self.quest_id, interaction.user.id, quest_title)
                        await approval_channel.send(embed=approval_embed, view=view)
                        
                logger.info(f"✅ Quest {self.quest_id} submitted by {interaction.user.display_name}")
            else:
                embed = create_error_embed("Submission Failed", "Failed to submit quest. You may not have accepted this quest or it's already submitted.")
                await interaction.followup.send(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"❌ Error in quest submission modal: {e}")
            embed = create_error_embed("Error", "Failed to submit quest. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=True)


class InteractiveBountyView(discord.ui.View):
    """Interactive view for bounty listings with pagination and quick actions"""
    
    def __init__(self, bounties, bounty_manager, user_id, guild_id, status_filter="active"):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bounties = bounties
        self.bounty_manager = bounty_manager
        self.user_id = user_id
        self.guild_id = guild_id
        self.status_filter = status_filter
        self.current_page = 0
        self.bounties_per_page = 3
        self.max_pages = math.ceil(len(bounties) / self.bounties_per_page) if bounties else 1
        
        self.update_buttons()
    
    def update_buttons(self):
        """Update button states based on current page"""
        # Clear existing bounty action buttons
        for item in self.children[:]:
            if hasattr(item, 'bounty_id'):
                self.remove_item(item)
        
        # Navigation buttons state
        self.previous_button.disabled = self.current_page <= 0
        self.next_button.disabled = self.current_page >= self.max_pages - 1
        
        # Add bounty action buttons for current page
        if self.bounties:
            start_idx = self.current_page * self.bounties_per_page
            end_idx = min(start_idx + self.bounties_per_page, len(self.bounties))
            current_bounties = self.bounties[start_idx:end_idx]
            
            for i, bounty in enumerate(current_bounties):
                if bounty['status'] == 'open':
                    # Claim button for open bounties
                    claim_button = discord.ui.Button(
                        label=f"Claim Bounty",
                        style=discord.ButtonStyle.success,
                        emoji="🎯",
                        row=2 + i
                    )
                    claim_button.bounty_id = bounty['bounty_id']
                    claim_button.callback = self.create_claim_callback(bounty['bounty_id'], bounty['title'])
                    self.add_item(claim_button)
                
                # Info button for all bounties
                info_button = discord.ui.Button(
                    label=f"View Details",
                    style=discord.ButtonStyle.secondary,
                    emoji="ℹ️",
                    row=2 + i
                )
                info_button.bounty_id = bounty['bounty_id']
                info_button.callback = self.create_info_callback(bounty)
                self.add_item(info_button)
    
    def create_claim_callback(self, bounty_id, title):
        """Create callback for claim button"""
        async def claim_callback(interaction):
            try:
                await interaction.response.defer(ephemeral=True)
                
                success, error = await self.bounty_manager.claim_bounty(bounty_id, self.user_id)
                
                if success:
                    embed = create_success_embed(
                        "Bounty Claimed!",
                        f"Successfully claimed bounty: **{title}**",
                        "Check `/my_bounties` to track your progress."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=True)
                    
                    # Refresh the bounty list
                    await self.refresh_bounties()
                    await self.update_embed(interaction)
                else:
                    embed = create_error_embed("Claim Failed", error or "Failed to claim bounty.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"❌ Error claiming bounty: {e}")
                embed = create_error_embed("Error", "Failed to claim bounty. Please try again.")
                await interaction.followup.send(embed=embed, ephemeral=True)
        return claim_callback
    
    def create_info_callback(self, bounty):
        """Create callback for info button"""
        async def info_callback(interaction):
            try:
                await interaction.response.defer(ephemeral=True)
                
                embed = create_info_embed(
                    f"Bounty: {bounty['title']}",
                    bounty['description']
                )
                
                embed.add_field(
                    name="■ Bounty Details",
                    value=f"**Reward**: {bounty['reward']}\n**Status**: {bounty['status'].title()}\n**Created**: <t:{int(bounty['created_at'].timestamp())}:R>",
                    inline=False
                )
                
                if bounty.get('completion_count', 0) > 0:
                    embed.add_field(
                        name="■ Progress",
                        value=f"**Completions**: {bounty['completion_count']} times",
                        inline=True
                    )
                
                await interaction.followup.send(embed=embed, ephemeral=True)
                
            except Exception as e:
                logger.error(f"❌ Error showing bounty details: {e}")
                embed = create_error_embed("Error", "Failed to get bounty details.")
                await interaction.followup.send(embed=embed, ephemeral=True)
        return info_callback
    
    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary, row=0)
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="▶ Next", style=discord.ButtonStyle.primary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.response.edit_message(embed=embed, view=self)
    
    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, row=1)
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh bounty list"""
        try:
            await interaction.response.defer()
            
            await self.refresh_bounties()
            self.update_buttons()
            embed = await self.create_page_embed(interaction.guild)
            await interaction.edit_original_response(embed=embed, view=self)
            
        except Exception as e:
            logger.error(f"❌ Error refreshing bounties: {e}")
    
    async def refresh_bounties(self):
        """Refresh bounty data"""
        if self.status_filter == "active":
            open_bounties = await self.bounty_manager.list_bounties(self.guild_id, "open")
            claimed_bounties = await self.bounty_manager.list_bounties(self.guild_id, "claimed")
            self.bounties = open_bounties + claimed_bounties
            self.bounties.sort(key=lambda x: x['created_at'], reverse=True)
        else:
            self.bounties = await self.bounty_manager.list_bounties(self.guild_id, self.status_filter)
        
        # Update pagination
        self.max_pages = math.ceil(len(self.bounties) / self.bounties_per_page) if self.bounties else 1
        if self.current_page >= self.max_pages:
            self.current_page = max(0, self.max_pages - 1)
    
    async def create_page_embed(self, guild):
        """Create embed for current page"""
        status_display = "Active" if self.status_filter == "active" else self.status_filter.title()
        embed = create_info_embed(
            f"Bounty Board - {status_display}",
            f"Found {len(self.bounties)} {status_display.lower()} bounties"
        )
        
        if not self.bounties:
            embed.add_field(
                name="■ No Bounties Found",
                value="No bounties match your criteria.",
                inline=False
            )
            return embed
        
        start_idx = self.current_page * self.bounties_per_page
        end_idx = min(start_idx + self.bounties_per_page, len(self.bounties))
        current_bounties = self.bounties[start_idx:end_idx]
        
        for bounty in current_bounties:
            creator = guild.get_member(bounty['creator_id'])
            creator_name = creator.display_name if creator else "Unknown"
            
            completion_count = bounty.get('completion_count', 0)
            
            status_emoji = {
                'open': '🟢',
                'claimed': '🟡',
                'submitted': '🟠',
                'cancelled': '🔴'
            }.get(bounty['status'], '⚪')
            
            value = f"**Creator**: {creator_name}\n**Reward**: {bounty['reward']}\n**Status**: {status_emoji} {bounty['status'].title()}"
            
            if completion_count > 0:
                value += f"\n**Completed**: {completion_count} times"
            
            embed.add_field(
                name=f"■ {bounty['title']}",
                value=value,
                inline=False
            )
        
        embed.set_footer(text=f"Page {self.current_page + 1} of {self.max_pages} • Use buttons to navigate and interact")
        return embed
    
    async def update_embed(self, interaction):
        """Update the embed after an action"""
        embed = await self.create_page_embed(interaction.guild)
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except:
            # If that fails, try followup
            await interaction.followup.edit_message(embed=embed, view=self)

class RankRequestView(discord.ui.View):
    """View for handling rank request approvals"""
    
    def __init__(self, request_user_id: int, role_id: int, username: str, bot_instance):
        super().__init__(timeout=None)
        self.request_user_id = request_user_id
        self.role_id = role_id
        self.username = username
        self.bot_instance = bot_instance
        
    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="✅")
    async def accept_rank_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Accept the rank request"""
        try:
            # Import here to avoid circular imports
            from bot.utils import ROLE_REQUIREMENTS, SPECIAL_ROLES
            
            # Check if the role is valid
            if self.role_id not in ROLE_REQUIREMENTS:
                embed = create_error_embed("Invalid Role", "The requested role is not available for promotion.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                
            # Get the member who made the request
            member = interaction.guild.get_member(self.request_user_id)
            if not member:
                embed = create_error_embed("Member Not Found", "The member who requested this rank is no longer in the server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get the target role
            target_role = interaction.guild.get_role(self.role_id)
            if not target_role:
                embed = create_error_embed("Role Not Found", "The requested role no longer exists on this server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if member already has this role
            if target_role in member.roles:
                embed = create_info_embed("Already Has Role", f"{member.display_name} already has the {target_role.name} role.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Remove conflicting rank roles (comprehensive cleanup)
            roles_to_remove = []
            from bot.utils import DISCIPLE_ROLES
            
            # Get bot's highest role for permission checking
            bot_member = interaction.guild.get_member(self.bot_instance.user.id)
            if not bot_member:
                embed = create_error_embed("Bot Error", "Cannot verify bot permissions.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            bot_top_role = bot_member.top_role
            
            # Only remove DISCIPLE_ROLES (progression ranks), never special roles
            for user_role in member.roles:
                if (user_role.id in DISCIPLE_ROLES and 
                    user_role.id != self.role_id):
                    # Check if bot can manage this role
                    if user_role.position >= bot_top_role.position:
                        embed = create_error_embed("Permission Error", f"I cannot remove the {user_role.name} role (role hierarchy).")
                        await interaction.response.send_message(embed=embed, ephemeral=True)
                        return
                    roles_to_remove.append(user_role)
            
            # Check if bot can manage target role
            if target_role.position >= bot_top_role.position:
                embed = create_error_embed("Permission Error", f"I cannot assign the {target_role.name} role (role hierarchy).")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
                    
            # Log role cleanup for audit trail
            if roles_to_remove:
                role_names = [role.name for role in roles_to_remove]
                logger.info(f"🧹 Rank promotion for {member.display_name} ({member.id}): removing {role_names}, adding {target_role.name}")
            else:
                logger.info(f"🎯 Rank promotion for {member.display_name} ({member.id}): adding {target_role.name} (no roles to remove)")
            
            # Check bot permissions proactively
            if not interaction.guild.me.guild_permissions.manage_roles:
                embed = create_error_embed("Permission Error", "I don't have the 'Manage Roles' permission.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Perform transactional role update to avoid partial failures
            try:
                # Build final role list properly (exclude @everyone, use list not set)
                final_roles = []
                roles_to_remove_set = set(roles_to_remove)
                
                # Add all current roles except @everyone and roles to remove
                for role in member.roles:
                    if not role.is_default() and role not in roles_to_remove_set:
                        final_roles.append(role)
                
                # Add target role if not already present
                if target_role not in final_roles:
                    final_roles.append(target_role)
                
                # Transactional role update
                await member.edit(roles=final_roles, reason=f"Rank promotion approved by {interaction.user.display_name} ({interaction.user.id})")
                
                # Log successful promotion with full audit details
                logger.info(f"✅ Rank promotion completed for {member.display_name} ({member.id}) in guild {interaction.guild.name} ({interaction.guild.id}): approved by {interaction.user.display_name} ({interaction.user.id}), target role: {target_role.name}")
                
            except discord.HTTPException as e:
                logger.error(f"❌ HTTP error during transactional role update for {member.id} in guild {interaction.guild.id}: {e}")
                
                # Fallback to sequential role operations for manageable DISCIPLE_ROLES only
                try:
                    logger.info(f"🔄 Attempting fallback sequential role operations for {member.display_name}")
                    
                    # Remove manageable disciple roles only
                    manageable_roles_to_remove = [r for r in roles_to_remove if r.position < bot_top_role.position]
                    if manageable_roles_to_remove:
                        await member.remove_roles(*manageable_roles_to_remove, reason=f"Fallback: removing old ranks for {interaction.user.display_name}")
                    
                    await member.add_roles(target_role, reason=f"Fallback: rank promotion by {interaction.user.display_name}")
                    logger.info(f"✅ Fallback promotion completed for {member.display_name} ({member.id})")
                    
                except discord.HTTPException as fallback_error:
                    logger.error(f"❌ Fallback also failed for {member.id}: {fallback_error}")
                    embed = create_error_embed("Role Assignment Failed", f"Both transactional and fallback role updates failed: {str(fallback_error)}")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
            
            # Update the embed to show approval
            embed = discord.Embed(
                title="🎉 RANK REQUEST APPROVED",
                description=f"**{member.display_name}** has been promoted to **{target_role.name}**",
                color=Colors.SUCCESS,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Approved by", value=interaction.user.display_name, inline=True)
            embed.add_field(name="Username", value=self.username, inline=True)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            logger.info(f"✅ Rank request approved: {member.id} promoted to {target_role.name} by {interaction.user.id}")
            
        except discord.Forbidden:
            embed = create_error_embed("Permission Error", "I don't have permission to manage roles.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"❌ Error approving rank request: {e}")
            embed = create_error_embed("Error", f"An error occurred while approving the rank request: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject_rank_request(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reject the rank request"""
        try:
            if not interaction.guild:
                await interaction.response.send_message("Error: Guild not found", ephemeral=True)
                return
            member = interaction.guild.get_member(self.request_user_id)
            member_name = member.display_name if member else "Unknown Member"
            
            # Update the embed to show rejection
            embed = discord.Embed(
                title="❌ RANK REQUEST REJECTED",
                description=f"**{member_name}**'s rank request has been rejected",
                color=Colors.ERROR,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="Rejected by", value=interaction.user.display_name, inline=True)
            embed.add_field(name="Username", value=self.username, inline=True)
            
            # Disable buttons
            for item in self.children:
                item.disabled = True
            
            await interaction.response.edit_message(embed=embed, view=self)
            
            logger.info(f"✅ Rank request rejected: {self.request_user_id} rejected by {interaction.user.id}")
            
        except Exception as e:
            logger.error(f"❌ Error rejecting rank request: {e}")
            embed = create_error_embed("Error", f"An error occurred while rejecting the rank request: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

class LeaderboardView(discord.ui.View):
    """Enhanced leaderboard view with improved pagination and mystat functionality"""

    def __init__(self, guild_id, leaderboard_manager, per_page=50):
        super().__init__(timeout=None)  # Persistent view - never expires
        self.guild_id = guild_id
        self.leaderboard_manager = leaderboard_manager
        self.per_page = per_page
        self.current_page = 1
        self.total_pages = 1
        self.leaderboard_data = []
        self.guild = None
        self.total_guild_points = 0
        self.is_active = True
        self.message = None  # Store message reference for auto-updates

        # Set custom_id for persistence (only if guild_id is valid)
        if guild_id > 0:
            self.custom_id = f"leaderboard_{guild_id}"

        # Add to active views list
        active_leaderboard_views.append(self)

    async def fetch_leaderboard_data(self):
        """Fetch current leaderboard data"""
        try:
            self.leaderboard_data, self.current_page, self.total_pages = await self.leaderboard_manager._get_leaderboard_async(
                self.guild_id, self.current_page, self.per_page
            )

            # Get guild object for member data
            if hasattr(self.leaderboard_manager, 'bot'):
                self.guild = self.leaderboard_manager.bot.get_guild(self.guild_id)

            # Get total guild points
            self.total_guild_points = await get_total_guild_points(self.leaderboard_manager, self.guild_id)

            logger.debug(f"✅ Fetched leaderboard data for guild {self.guild_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error fetching leaderboard data: {e}")
            return False

    async def update_embed(self, interaction):
        """Update the leaderboard embed"""
        try:
            guild_name = self.guild.name if self.guild else "Unknown Guild"
            embed = create_leaderboard_embed(
                self.leaderboard_data, 
                self.current_page, 
                self.total_pages, 
                guild_name,
                self.guild,
                self.total_guild_points
            )

            # Update button states
            self.update_button_states()

            # Use the correct method based on interaction state
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)

        except Exception as e:
            logger.error(f"❌ Error updating leaderboard embed: {e}")
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("An error occurred while updating the leaderboard.", ephemeral=False)
                else:
                    await interaction.response.send_message("An error occurred while updating the leaderboard.", ephemeral=False)
            except:
                logger.error("❌ Failed to send error message to user")

    def update_button_states(self):
        """Update button enabled/disabled states"""
        # Previous page button
        for item in self.children:
            if hasattr(item, 'label') and 'Previous' in str(item.label):
                item.disabled = (self.current_page <= 1)
            elif hasattr(item, 'label') and 'Next' in str(item.label):
                item.disabled = (self.current_page >= self.total_pages)

    async def auto_update_leaderboard(self):
        """Auto-update leaderboard data without user interaction"""
        try:
            # Safety check - ensure view is still active
            if not hasattr(self, 'is_active') or not self.is_active:
                logger.debug(f"🔄 Skipping auto-update for inactive view (guild {self.guild_id})")
                return

            # Safety check - ensure we have a message to update
            if not hasattr(self, 'message') or not self.message:
                logger.debug(f"🔄 No message to update for guild {self.guild_id}")
                return

            # Fetch fresh leaderboard data with error handling
            try:
                success = await self.fetch_leaderboard_data()
                if not success:
                    logger.debug(f"🔄 Failed to fetch leaderboard data for guild {self.guild_id}")
                    return
            except Exception as e:
                logger.debug(f"Error fetching leaderboard data: {e}")
                return

            # Safely get guild information
            guild = self.guild
            guild_name = f"Guild {self.guild_id}"
            
            try:
                if guild and hasattr(guild, 'name'):
                    guild_name = guild.name
                elif not guild:
                    # Try to get guild from the bot instance via leaderboard_manager
                    try:
                        if hasattr(self.leaderboard_manager, 'bot') and self.leaderboard_manager.bot:
                            found_guild = self.leaderboard_manager.bot.get_guild(self.guild_id)
                            if found_guild:
                                guild = found_guild
                                guild_name = guild.name
                                self.guild = guild  # Cache for future use
                                logger.debug(f"✅ Retrieved guild {guild_name} for auto-update")
                    except Exception as e:
                        logger.debug(f"Failed to retrieve guild: {e}")
                        pass
            except Exception as e:
                logger.debug(f"Error getting guild info: {e}")

            # Create updated embed with enhanced error handling
            try:
                embed = create_leaderboard_embed(
                    self.leaderboard_data, 
                    self.current_page, 
                    self.total_pages, 
                    guild_name,
                    guild,
                    self.total_guild_points
                )
            except Exception as e:
                logger.warning(f"⚠️ Error creating leaderboard embed: {e}")
                return

            # Update button states safely
            try:
                self.update_button_states()
            except Exception as e:
                logger.debug(f"Error updating button states: {e}")

            # Update the message with comprehensive error handling
            try:
                await self.message.edit(embed=embed, view=self)
                logger.debug(f"✅ Auto-updated leaderboard message for guild {self.guild_id}")

            except discord.NotFound:
                # Message was deleted, mark view as inactive
                self.is_active = False
                if self in active_leaderboard_views:
                    active_leaderboard_views.remove(self)
                logger.debug(f"ℹ️ Leaderboard message deleted, removed view for guild {self.guild_id}")

            except discord.HTTPException as e:
                if e.status == 404:
                    # Message not found
                    self.is_active = False
                    if self in active_leaderboard_views:
                        active_leaderboard_views.remove(self)
                    logger.debug(f"ℹ️ Leaderboard message not found, removed view for guild {self.guild_id}")
                else:
                    logger.debug(f"HTTP error auto-updating leaderboard (non-critical): {e}")

            except discord.Forbidden:
                logger.debug(f"No permission to edit leaderboard message for guild {self.guild_id}")
                # Don't mark as inactive, permission might be restored

            except Exception as e:
                logger.debug(f"Non-critical error auto-updating leaderboard message: {e}")
                # Don't crash, just log and continue

        except Exception as e:
            logger.debug(f"Non-critical error in auto_update_leaderboard: {e}")
            # Changed from error to debug - this shouldn't crash the bot

    @discord.ui.button(label="◀️ Previous", style=discord.ButtonStyle.secondary)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to previous page"""
        if self.current_page > 1:
            self.current_page -= 1
            await self.fetch_leaderboard_data()
            await self.update_embed(interaction)

    @discord.ui.button(label="▶️ Next", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Go to next page"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            await self.fetch_leaderboard_data()
            await self.update_embed(interaction)

    @discord.ui.button(label="📊 My Stats", style=discord.ButtonStyle.primary)
    async def my_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Show user's personal statistics"""
        try:
            user_data = await self.leaderboard_manager.get_user_stats(self.guild_id, interaction.user.id)
            
            if not user_data:
                embed = create_error_embed(
                    "No Stats Found",
                    "You don't have any statistics yet. Start participating to build your profile!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            embed = create_user_stats_embed(interaction.user, user_data, interaction.guild.name)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"❌ Error getting user stats: {e}")
            embed = create_error_embed(
                "Error",
                "Failed to retrieve your statistics. Please try again later."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.success)
    async def refresh_leaderboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Refresh leaderboard data"""
        await self.fetch_leaderboard_data()
        await self.update_embed(interaction)


class UnifiedBotCommands(commands.Cog):
    """Unified command handlers for Quest and Leaderboard systems"""

    def __init__(self, bot: commands.Bot, quest_manager: QuestManager,
                 channel_config: ChannelConfig, user_stats_manager: UserStatsManager,
                 leaderboard_manager, role_reward_manager=None, team_quest_manager=None,
                 bounty_manager=None):
        self.bot = bot
        self.quest_manager = quest_manager
        self.channel_config = channel_config
        self.user_stats_manager = user_stats_manager
        self.leaderboard_manager = leaderboard_manager
        self.role_reward_manager = role_reward_manager
        self.team_quest_manager = team_quest_manager
        self.bounty_manager = bounty_manager


    def _get_rank_color(self, rank: str) -> discord.Color:
        """Get color based on quest rank"""
        colors = {
            QuestRank.EASY: discord.Color.green(),
            QuestRank.NORMAL: discord.Color.blue(),
            QuestRank.MEDIUM: discord.Color.orange(),
            QuestRank.HARD: discord.Color.red(),
            QuestRank.IMPOSSIBLE: discord.Color.purple()
        }
        return colors.get(rank, discord.Color.light_grey())

    def _get_status_color(self, status: str) -> discord.Color:
        """Get color based on quest status"""
        colors = {
            QuestStatus.AVAILABLE: discord.Color.green(),
            QuestStatus.ACCEPTED: discord.Color.yellow(),
            QuestStatus.COMPLETED: discord.Color.orange(),
            QuestStatus.APPROVED: discord.Color.blue(),
            QuestStatus.REJECTED: discord.Color.red(),
            QuestStatus.CANCELLED: discord.Color.dark_grey()
        }
        return colors.get(status, discord.Color.light_grey())

    # QUEST COMMANDS
    @app_commands.command(name="setup_channels", description="Setup quest channels for the server")
    @app_commands.describe(
        quest_list_channel="Channel for quest listings",
        quest_accept_channel="Channel for quest acceptance",
        quest_submit_channel="Channel for quest submissions",
        quest_approval_channel="Channel for quest approvals",
        notification_channel="Channel for notifications",
        retirement_channel="Channel for retirement notifications",
        rank_request_channel="Channel for rank promotion requests",
        bounty_channel="Channel for bounty announcements",
        bounty_approval_channel="Channel for bounty submission approvals",
        mentor_quest_channel="Channel for mentor quest submissions (optional)",
        funeral_channel="Channel for funeral notifications (optional)",
        reincarnation_channel="Channel for reincarnation notifications (optional)",
        announcement_channel="Channel for sect announcements (optional)"
    )
    async def setup_channels(self, interaction: discord.Interaction,
                             quest_list_channel: discord.TextChannel,
                             quest_accept_channel: discord.TextChannel,
                             quest_submit_channel: discord.TextChannel,
                             quest_approval_channel: discord.TextChannel,
                             notification_channel: discord.TextChannel,
                             retirement_channel: discord.TextChannel,
                             rank_request_channel: discord.TextChannel,
                             bounty_channel: discord.TextChannel,
                             bounty_approval_channel: discord.TextChannel,
                             mentor_quest_channel: discord.TextChannel = None,
                             funeral_channel: discord.TextChannel = None,
                             reincarnation_channel: discord.TextChannel = None,
                             announcement_channel: discord.TextChannel = None):
        """Setup quest channels for the server"""
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        if not has_quest_creation_permission(interaction.user, interaction.guild):
            await interaction.response.send_message("You don't have permission to setup channels!", ephemeral=False)
            return

        embed = discord.Embed(
            title="Channel Configuration Complete",
            description="Quest channels have been successfully configured for this server.",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="Quest List Channel",
            value=f"{quest_list_channel.mention}\nNew quests will be posted here",
            inline=False
        )
        embed.add_field(
            name="Quest Accept Channel",
            value=f"{quest_accept_channel.mention}\nUse this channel to accept quests",
            inline=False
        )
        embed.add_field(
            name="Quest Submit Channel",
            value=f"{quest_submit_channel.mention}\nSubmit completed quests here",
            inline=False
        )
        embed.add_field(
            name="Quest Approval Channel",
            value=f"{quest_approval_channel.mention}\nQuest approvals will be processed here",
            inline=False
        )
        embed.add_field(
            name="Notification Channel",
            value=f"{notification_channel.mention}\nGeneral quest notifications will appear here",
            inline=False
        )
        embed.add_field(
            name="Retirement Channel",
            value=f"{retirement_channel.mention}\nRetirement notifications will be sent here",
            inline=False
        )
        
        embed.add_field(
            name="Rank Request Channel",
            value=f"{rank_request_channel.mention}\nRank promotion requests will be sent here",
            inline=False
        )
        embed.add_field(
            name="Bounty Channel",
            value=f"{bounty_channel.mention}\nNew bounties will be announced here",
            inline=False
        )
        embed.add_field(
            name="Bounty Approval Channel",
            value=f"{bounty_approval_channel.mention}\nBounty submissions will be sent here for review",
            inline=False
        )
        
        if mentor_quest_channel:
            embed.add_field(
                name="Mentor Quest Channel",
                value=f"{mentor_quest_channel.mention}\nMentor quest submissions will be posted here with mentor pings",
                inline=False
            )
        
        if funeral_channel:
            embed.add_field(
                name="Funeral Channel",
                value=f"{funeral_channel.mention}\nFuneral notifications for departing members",
                inline=False
            )
        
        if reincarnation_channel:
            embed.add_field(
                name="Reincarnation Channel",
                value=f"{reincarnation_channel.mention}\nReincarnation notifications for returning members",
                inline=False
            )
        
        if announcement_channel:
            embed.add_field(
                name="Announcement Channel",
                value=f"{announcement_channel.mention}\nOfficial sect announcements will be posted here",
                inline=False
            )

        embed.set_footer(text=f"Configured by {interaction.user.display_name}")
        embed.timestamp = datetime.now()

        await interaction.response.send_message(embed=embed)

        # Set channels in database after responding
        await self.channel_config.set_guild_channels(
            interaction.guild.id,
            quest_list_channel.id,
            quest_accept_channel.id,
            quest_submit_channel.id,
            quest_approval_channel.id,
            notification_channel.id,
            retirement_channel.id,
            rank_request_channel.id,
            bounty_channel.id,
            bounty_approval_channel.id,
            mentor_quest_channel.id if mentor_quest_channel else None,
            funeral_channel.id if funeral_channel else None,
            reincarnation_channel.id if reincarnation_channel else None,
            announcement_channel.id if announcement_channel else None
        )

    @app_commands.command(name="announce", description="Send an official announcement to the sect")
    @app_commands.describe(
        announcement_type="Type of announcement",
        title="Announcement title",
        description="Main announcement content"
    )
    @app_commands.choices(announcement_type=[
        app_commands.Choice(name="General - Regular sect communications", value="general"),
        app_commands.Choice(name="Event - Sect events and gatherings", value="event"),
        app_commands.Choice(name="Mission - Mission briefings and urgent quests", value="mission"),
        app_commands.Choice(name="Celebration - Achievements and celebrations", value="celebration"),
        app_commands.Choice(name="Warning - Disciplinary actions and warnings", value="warning"),
        app_commands.Choice(name="Decree - Supreme authority proclamations", value="decree")
    ])
    async def announce(self, interaction: discord.Interaction, 
                      announcement_type: str,
                      title: str, 
                      description: str):
        """Send an official sect announcement"""
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        # Check for admin permissions
        if not has_quest_creation_permission(interaction.user, interaction.guild):
            embed = create_error_embed("Permission Denied", "You don't have permission to send announcements!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Special permission check for decree announcements (highest ranks only)
        if announcement_type == "decree":
            user_has_high_rank = False
            special_roles = [1266143259801948261, 1281115906717650985, 1415022514534486136, 1304283446016868424, 1276607675735736452, 1415242286929022986]  # Demon God, Heavenly Demon, Demon Sovereign, Supreme Demon, Guardian, Demon King
            for role in interaction.user.roles:
                if role.id in special_roles:
                    user_has_high_rank = True
                    break
            
            if not user_has_high_rank:
                embed = create_error_embed("Insufficient Authority", "Decree announcements can only be issued by Demon God, Heavenly Demon, Demon Sovereign, Supreme Demon, Guardian, or Demon King ranks!")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
        
        # Get announcement channel
        announcement_channel_id = await self.channel_config.get_announcement_channel(interaction.guild.id)
        if not announcement_channel_id:
            embed = create_error_embed("Configuration Error", 
                                     "No announcement channel has been configured for this server. Please use `/setup_channels` to configure an announcement channel first.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        announcement_channel = interaction.guild.get_channel(announcement_channel_id)
        if not announcement_channel:
            embed = create_error_embed("Channel Not Found", 
                                     "The configured announcement channel could not be found. Please reconfigure using `/setup_channels`.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Get user's points for authority level determination
        user_stats = await self.leaderboard_manager.get_user_stats(interaction.user.id, interaction.guild.id)
        user_points = user_stats.get('points', 0) if user_stats else 0
        
        # Create the announcement embed with dynamic authority and type
        from bot.utils import create_announcement_embed
        announcement_embed = create_announcement_embed(
            title=title,
            description=description,
            author_name=interaction.user.display_name,
            author_member=interaction.user,
            author_points=user_points,
            announcement_type=announcement_type
        )
        
        try:
            # Send announcement with role ping
            announcement_role = interaction.guild.get_role(1266122008102703175)
            role_mention = announcement_role.mention if announcement_role else "@everyone"
            
            # Send to announcement channel
            await announcement_channel.send(
                content=f"{role_mention}\n\n",
                embed=announcement_embed
            )
            
            # Confirm to the user
            success_embed = create_success_embed(
                "Announcement Sent",
                f"Your announcement '{title}' has been successfully posted to {announcement_channel.mention}.",
                additional_info=f"The announcement was sent with role notification and will be visible to all sect members."
            )
            await interaction.response.send_message(embed=success_embed, ephemeral=True)
            
        except discord.Forbidden:
            embed = create_error_embed("Permission Error", 
                                     f"I don't have permission to send messages in {announcement_channel.mention}. Please check my permissions.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.HTTPException as e:
            embed = create_error_embed("Send Error", 
                                     f"Failed to send announcement: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)



    @app_commands.command(name="create_quest", description="Create a new quest")
    @app_commands.describe(
        title="Quest title",
        description="Quest description",
        requirements="Quest requirements (optional)",
        reward="Quest reward - include number (e.g., '50 - special collector badge')",
        rank="Quest difficulty rank",
        category="Quest category",
        is_team_quest="Create as team quest (optional)",
        team_size="Required team size if team quest (2-10 members)"
    )
    @app_commands.choices(rank=[
        app_commands.Choice(name="Easy", value=QuestRank.EASY),
        app_commands.Choice(name="Normal", value=QuestRank.NORMAL),
        app_commands.Choice(name="Medium", value=QuestRank.MEDIUM),
        app_commands.Choice(name="Hard", value=QuestRank.HARD),
        app_commands.Choice(name="Impossible", value=QuestRank.IMPOSSIBLE)
    ])
    @app_commands.choices(category=[
        app_commands.Choice(name="Hunting", value=QuestCategory.HUNTING),
        app_commands.Choice(name="Collecting", value=QuestCategory.COLLECTING),
        app_commands.Choice(name="Gathering", value=QuestCategory.GATHERING),
        app_commands.Choice(name="Social", value=QuestCategory.SOCIAL),
        app_commands.Choice(name="Survival", value=QuestCategory.SURVIVAL)
    ])
    async def create_quest(self, interaction: discord.Interaction,
                          title: str,
                          description: str,
                          requirements: str = "",
                          reward: str = "",
                          rank: str = QuestRank.NORMAL,
                          category: str = QuestCategory.OTHER,
                          is_team_quest: bool = False,
                          team_size: int = 2):
        """Create a new quest"""
        try:
            # Defer the response immediately to prevent timeout
            await interaction.response.defer(ephemeral=False)
            
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.followup.send(embed=embed)
                return
            
            if not has_quest_creation_permission(interaction.user, interaction.guild):
                embed = create_error_embed("Permission Denied", "You don't have permission to create quests!")
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            # Validate team quest parameters
            if is_team_quest:
                if not self.team_quest_manager:
                    embed = create_error_embed("Feature Unavailable", "Team quests are not enabled on this server.")
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    return
                
                if not 2 <= team_size <= 10:
                    embed = create_error_embed("Invalid Team Size", "Team size must be between 2 and 10 members.")
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    return

            # Validate and preview reward points
            extracted_points = self._extract_points_from_reward(reward) if reward else 10
            
            # Create the quest
            quest = await self.quest_manager.create_quest(
                title=title,
                description=description,
                creator_id=interaction.user.id,
                guild_id=interaction.guild.id,
                requirements=requirements,
                reward=reward,
                rank=rank,
                category=category
            )

            # Create team if this is a team quest
            team = None
            if is_team_quest:
                try:
                    # Create team without a leader - first person to accept becomes leader
                    team = await self.team_quest_manager.create_team_quest(
                        quest.quest_id, team_size, None, interaction.guild.id
                    )
                except ValueError as e:
                    # If team creation fails, continue with regular quest
                    logger.warning(f"Team creation failed for quest {quest.quest_id}: {e}")
                    embed = create_error_embed("Team Creation Failed", f"Quest created but team failed: {str(e)}")
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    return
                except Exception as e:
                    # If team creation fails, continue with regular quest
                    logger.error(f"❌ Error creating team for quest {quest.quest_id}: {e}")
                    embed = create_error_embed("Error", "Quest created but team creation failed. You can still use the quest as a regular quest.")
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    return

            # Create beautiful quest embed for quest list channel
            embed = discord.Embed(
                title="NEW QUEST AVAILABLE",
                description=f"**{quest.title}**",
                color=get_quest_rank_color(quest.rank)
            )
            
            embed.add_field(
                name="■ Description",
                value=f"```\n{quest.description}\n```",
                inline=False
            )
            
            # Quest info section with better formatting
            quest_info = f"**Quest ID:** `{quest.quest_id}`\n**Difficulty:** {quest.rank.title()}\n**Category:** {quest.category.title()}"
            if is_team_quest and team:
                quest_info += f"\n**Type:** Team Quest\n**Team Size:** {team_size} members required"
            embed.add_field(
                name="■ Quest Information",
                value=quest_info,
                inline=True
            )
            
            # Status indicator
            if is_team_quest and team:
                status_text = f"**{quest.status.title()}**\nTeam Created - Use `/join_team {quest.quest_id}` to join"
            else:
                status_text = f"**{quest.status.title()}**\nReady to Accept"
            
            embed.add_field(
                name="■ Status",
                value=status_text,
                inline=True
            )
            
            # Empty field for spacing
            embed.add_field(name="\u200b", value="\u200b", inline=True)
            
            if quest.requirements:
                embed.add_field(
                    name="■ Requirements",
                    value=f"```yaml\n{quest.requirements}\n```",
                    inline=False
                )
            
            if quest.reward:
                embed.add_field(
                    name="■ Reward",
                    value=f"```yaml\n{quest.reward}\n```",
                    inline=False
                )
                
                # Add points preview field
                embed.add_field(
                    name="■ Points Preview", 
                    value=f"This quest will award **{extracted_points}** when completed",
                    inline=False
                )
            
            # Add team information if this is a team quest
            if is_team_quest and team:
                embed.add_field(
                    name="■ Team Information",
                    value=f"**Members:** {team_size}\n\nUse `/join_team {quest.quest_id}` to join this team!",
                    inline=False
                )
            
            embed.set_author(
                name=f"Quest Creator: {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None
            )
            
            embed.set_footer(text=f"Heavenly Demon Sect • Created by {interaction.user.display_name}")

            await interaction.followup.send(embed=embed)

            # Post to quest list channel if configured
            quest_list_channel_id = await self.channel_config.get_quest_list_channel(interaction.guild.id)
            if quest_list_channel_id:
                quest_list_channel = self.bot.get_channel(quest_list_channel_id)
                if quest_list_channel:
                    await quest_list_channel.send(embed=embed)
                    
        except Exception as e:
            logger.error(f"❌ Error in create_quest command: {e}")
            embed = create_error_embed("Quest Creation Failed", "An unexpected error occurred while creating the quest. Please try again.")
            try:
                # Always use followup since we deferred the response at the beginning
                await interaction.followup.send(embed=embed, ephemeral=True)
            except Exception as followup_error:
                logger.error(f"❌ Failed to send error message for create_quest: {followup_error}")
                # If followup fails, try one more time with a simple message
                try:
                    if not interaction.response.is_done():
                        await interaction.response.send_message("❌ Quest creation failed. Please try again.", ephemeral=True)
                except Exception as final_error:
                    logger.error(f"❌ Final error handling failed for create_quest: {final_error}")

    @app_commands.command(name="accept_quest", description="Accept a quest")
    @app_commands.describe(quest_id="The quest ID to accept")
    async def accept_quest(self, interaction: discord.Interaction, quest_id: str):
        """Accept a quest"""
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=False)
        
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.followup.send(embed=embed)
            return
        
        try:
            user_role_ids = [role.id for role in interaction.user.roles]
            progress, error = await self.quest_manager.accept_quest(
                quest_id, interaction.user.id, user_role_ids, interaction.channel.id
            )

            if error:
                embed = create_error_embed("Quest Acceptance Failed", error)
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            # Update user stats
            await self.user_stats_manager.update_quest_accepted(interaction.user.id, interaction.guild.id)
            
            # Update leaderboard stats
            await self.leaderboard_manager.update_user_quest_stats(
                interaction.guild.id, interaction.user.id, interaction.user.display_name,
                quest_accepted=True
            )

            quest = await self.quest_manager.get_quest(quest_id)
            quest_title = quest.title if quest else "Unknown Quest"
            
            # Check if this is a team quest and automatically create/join team
            team_message = ""
            if self.team_quest_manager:
                # Check if team already exists for this quest
                existing_team = await self.team_quest_manager.get_team_status(quest_id)
                
                if existing_team:
                    # Team exists, try to join it
                    success, join_message = await self.team_quest_manager.join_team(
                        quest_id, interaction.user.id, interaction.guild.id
                    )
                    if success:
                        team_message = f"\n🤝 **Team Update:** {join_message}"
                        # Check if team is now complete
                        updated_team = await self.team_quest_manager.get_team_status(quest_id)
                        if updated_team and updated_team.is_team_complete:
                            team_message += f"\n✅ **Team Complete:** All {updated_team.team_size_required} members joined!"
                    else:
                        team_message = f"\n⚠️ **Team Status:** {join_message}"
                else:
                    # Check if this quest was created as a team quest by looking for "team" keywords
                    # or checking if there's a team size specified in requirements/description
                    quest_text = f"{quest.title} {quest.description} {quest.requirements or ''}".lower()
                    if any(keyword in quest_text for keyword in ["team", "group", "together", "members", "people"]):
                        # Extract team size from text (default to 2 if not found)
                        team_size = 2
                        import re
                        size_match = re.search(r'(\d+)\s*(?:member|people|person)', quest_text)
                        if size_match:
                            team_size = min(max(int(size_match.group(1)), 2), 10)  # Between 2-10
                        
                        try:
                            # Create team with the user as the first member
                            new_team = await self.team_quest_manager.create_team_quest(
                                quest_id, team_size, interaction.user.id, interaction.guild.id
                            )
                            team_message = f"\n🎯 **Team Created:** You're now the team leader! ({len(new_team.team_members)}/{team_size} members)"
                            team_message += f"\n📢 **Recruitment:** Other users can join with `/join_team {quest_id}`"
                        except Exception as e:
                            logger.warning(f"Failed to auto-create team for quest {quest_id}: {e}")
            
            embed = create_success_embed(
                "Quest Accepted!",
                f"You have successfully accepted the quest: **{quest_title}**",
                f"Quest ID: `{quest_id}`\nRemember to submit proof when completed!{team_message}"
            )

            await interaction.followup.send(embed=embed, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error in accept_quest: {e}")
            embed = create_error_embed("System Error", "An unexpected error occurred. Please try again.")
            try:
                await interaction.followup.send(embed=embed, ephemeral=False)
            except:
                # If followup also fails, log the error
                logger.error(f"❌ Failed to send error message for accept_quest: {e}")

    @app_commands.command(name="sync_commands", description="Sync slash commands (Admin only)")
    @app_commands.describe(guild_only="Whether to sync only for this guild (faster)")
    async def sync_commands(self, interaction: discord.Interaction, guild_only: bool = True):
        """Manually sync slash commands"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            embed = create_error_embed("Permission Denied", "You need administrator permissions to use this command.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            
            if guild_only and interaction.guild:
                # Sync for current guild only (faster)
                synced = await self.bot.tree.sync(guild=interaction.guild)
                embed = create_success_embed(
                    "Commands Synced", 
                    f"Successfully synced {len(synced)} commands for this server. They should appear immediately."
                )
            else:
                # Global sync (takes up to 1 hour to appear)
                synced = await self.bot.tree.sync()
                embed = create_success_embed(
                    "Commands Synced Globally", 
                    f"Successfully synced {len(synced)} commands globally. It may take up to 1 hour for them to appear in all servers."
                )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            logger.error(f"Error syncing commands: {e}")
            embed = create_error_embed("Sync Failed", f"Failed to sync commands: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list_quests", description="List all available quests")
    @app_commands.describe(
        rank_filter="Filter by quest rank",
        category_filter="Filter by quest category",
        show_all="Show all quests including completed ones"
    )
    @app_commands.choices(rank_filter=[
        app_commands.Choice(name="Easy", value=QuestRank.EASY),
        app_commands.Choice(name="Normal", value=QuestRank.NORMAL),
        app_commands.Choice(name="Medium", value=QuestRank.MEDIUM),
        app_commands.Choice(name="Hard", value=QuestRank.HARD),
        app_commands.Choice(name="Impossible", value=QuestRank.IMPOSSIBLE)
    ])
    @app_commands.choices(category_filter=[
        app_commands.Choice(name="Hunting", value=QuestCategory.HUNTING),
        app_commands.Choice(name="Collecting", value=QuestCategory.COLLECTING),
        app_commands.Choice(name="Gathering", value=QuestCategory.GATHERING),
        app_commands.Choice(name="Social", value=QuestCategory.SOCIAL),
        app_commands.Choice(name="Survival", value=QuestCategory.SURVIVAL)
    ])
    async def list_quests(self, interaction: discord.Interaction,
                          rank_filter: str = None,
                          category_filter: str = None,
                          show_all: bool = False):
        """List all available quests with optional filters"""
        await interaction.response.defer(ephemeral=False)

        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.followup.send(embed=embed, ephemeral=False)
            return
            
        # Get quests based on filter
        if show_all:
            quests = await self.quest_manager.get_guild_quests(interaction.guild.id)
        else:
            quests = await self.quest_manager.get_available_quests(interaction.guild.id)

        # Apply filters
        if rank_filter:
            quests = [q for q in quests if q.rank == rank_filter]
        if category_filter:
            quests = [q for q in quests if q.category == category_filter]

        if not quests:
            embed = create_info_embed(
                "No Quests Found",
                "No quests match your current filters.",
                "Try adjusting your search criteria or check back later for new adventures."
            )
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        # Create paginated quest list
        embed = discord.Embed(
            title=f"Quest Board - {interaction.guild.name}",
            description=f"**{len(quests)}** quest{'s' if len(quests) != 1 else ''} found",
            color=Colors.SECONDARY
        )

        # Add quests (limit to 10 for readability)
        for i, quest in enumerate(quests[:10]):
            status_text = quest.status.title()
            
            # Check if this is a team quest
            team_status = None
            if self.team_quest_manager:
                team_status = await self.team_quest_manager.get_team_status(quest.quest_id)
            
            quest_info = f"**Difficulty:** {quest.rank.title()}\n**Category:** {quest.category.title()}\n**Status:** {status_text}"
            
            # Add team information
            if team_status:
                quest_info += f"\n**Type:** Team Quest ({team_status.team_size_required} members)"
            else:
                quest_info += f"\n**Type:** Solo Quest"
            
            if quest.reward:
                reward_preview = quest.reward[:40] + '...' if len(quest.reward) > 40 else quest.reward
                quest_info += f"\n**Reward:** {reward_preview}"

            embed.add_field(
                name=f"■ {quest.title}",
                value=f"```yaml\nID: {quest.quest_id}\n```{quest_info}",
                inline=True
            )

        if len(quests) > 10:
            embed.add_field(
                name="■ Additional Information",
                value=f"Showing first 10 of {len(quests)} quests. Use filters to narrow down results.",
                inline=False
            )
        
        # Add filter info with better formatting
        filter_info = []
        if rank_filter:
            filter_info.append(f"**Difficulty:** {rank_filter.title()}")
        if category_filter:
            filter_info.append(f"**Category:** {category_filter.title()}")
        if show_all:
            filter_info.append("**Scope:** All Quests")
        else:
            filter_info.append("**Scope:** Available Only")

        if filter_info:
            embed.add_field(
                name="■ Active Filters",
                value=" • ".join(filter_info),
                inline=False
            )

        # Create interactive quest browser
        view = InteractiveQuestBrowser(
            quests=quests,
            quest_manager=self.quest_manager,
            team_quest_manager=self.team_quest_manager,
            user_id=interaction.user.id,
            guild_id=interaction.guild.id,
            rank_filter=rank_filter,
            category_filter=category_filter,
            show_all=show_all
        )
        
        embed.set_footer(text="Use the buttons below to navigate and interact with quests")
        await interaction.followup.send(embed=embed, view=view, ephemeral=False)

    @app_commands.command(name="search_quests", description="Search quests by keywords, title, or description")
    @app_commands.describe(
        keywords="Search keywords to find relevant quests",
        rank_filter="Filter by quest rank",
        category_filter="Filter by quest category"
    )
    @app_commands.choices(rank_filter=[
        app_commands.Choice(name="Easy", value=QuestRank.EASY),
        app_commands.Choice(name="Normal", value=QuestRank.NORMAL),
        app_commands.Choice(name="Medium", value=QuestRank.MEDIUM),
        app_commands.Choice(name="Hard", value=QuestRank.HARD),
        app_commands.Choice(name="Impossible", value=QuestRank.IMPOSSIBLE)
    ])
    @app_commands.choices(category_filter=[
        app_commands.Choice(name="Hunting", value=QuestCategory.HUNTING),
        app_commands.Choice(name="Collecting", value=QuestCategory.COLLECTING),
        app_commands.Choice(name="Gathering", value=QuestCategory.GATHERING),
        app_commands.Choice(name="Social", value=QuestCategory.SOCIAL),
        app_commands.Choice(name="Survival", value=QuestCategory.SURVIVAL)
    ])
    async def search_quests(self, interaction: discord.Interaction,
                           keywords: str,
                           rank_filter: str = None,
                           category_filter: str = None):
        """Search for quests using keywords"""
        await interaction.response.defer(ephemeral=False)

        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        try:
            # Get all available quests
            quests = await self.quest_manager.get_available_quests(interaction.guild.id)
            
            # Apply keyword search
            search_terms = keywords.lower().split()
            filtered_quests = []
            
            for quest in quests:
                # Search in title, description, and requirements
                search_text = f"{quest.title} {quest.description} {quest.requirements}".lower()
                
                # Check if any search term matches
                if any(term in search_text for term in search_terms):
                    filtered_quests.append(quest)
            
            # Apply additional filters
            if rank_filter:
                filtered_quests = [q for q in filtered_quests if q.rank == rank_filter]
            if category_filter:
                filtered_quests = [q for q in filtered_quests if q.category == category_filter]

            if not filtered_quests:
                embed = create_info_embed(
                    "No Matching Quests",
                    f"No quests found matching your search criteria.",
                    f"**Keywords**: {keywords}\n**Searched in**: Title, Description, Requirements\n\nTry different keywords or check `/list_quests` for all available quests."
                )
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            # Create search results with interactive browser
            view = InteractiveQuestBrowser(
                quests=filtered_quests,
                quest_manager=self.quest_manager,
                team_quest_manager=self.team_quest_manager,
                user_id=interaction.user.id,
                guild_id=interaction.guild.id,
                rank_filter=rank_filter,
                category_filter=category_filter,
                show_all=False
            )
            
            # Create search results embed
            embed = discord.Embed(
                title=f"🔍 Quest Search Results",
                description=f"**{len(filtered_quests)}** quest{'s' if len(filtered_quests) != 1 else ''} found matching your search",
                color=Colors.SUCCESS
            )
            
            # Add search info
            search_info = f"**Keywords**: {keywords}"
            if rank_filter:
                search_info += f"\n**Difficulty**: {rank_filter.title()}"
            if category_filter:
                search_info += f"\n**Category**: {category_filter.title()}"
            
            embed.add_field(
                name="■ Search Criteria",
                value=search_info,
                inline=False
            )
            
            # Show first few matching quests
            for i, quest in enumerate(filtered_quests[:3]):
                status_text = quest.status.title()
                
                # Check if this is a team quest
                team_status = None
                if self.team_quest_manager:
                    team_status = await self.team_quest_manager.get_team_status(quest.quest_id)
                
                quest_info = f"**Difficulty:** {quest.rank.title()}\n**Category:** {quest.category.title()}\n**Status:** {status_text}"
                
                # Add team information
                if team_status:
                    quest_info += f"\n**Type:** Team Quest ({team_status.team_size_required} members)"
                else:
                    quest_info += f"\n**Type:** Solo Quest"
                
                if quest.reward:
                    reward_preview = quest.reward[:40] + '...' if len(quest.reward) > 40 else quest.reward
                    quest_info += f"\n**Reward:** {reward_preview}"

                embed.add_field(
                    name=f"■ {quest.title}",
                    value=f"```yaml\nID: {quest.quest_id}\n```{quest_info}",
                    inline=True
                )

            if len(filtered_quests) > 3:
                embed.add_field(
                    name="■ Additional Results",
                    value=f"Showing first 3 of {len(filtered_quests)} results. Use navigation buttons to see more.",
                    inline=False
                )

            embed.set_footer(text="Use the buttons below to navigate and interact with search results")
            await interaction.followup.send(embed=embed, view=view, ephemeral=False)
            logger.info(f"✅ Search completed for '{keywords}' by {interaction.user.display_name}")

        except Exception as e:
            logger.error(f"❌ Error in quest search: {e}")
            embed = create_error_embed("Search Error", "Failed to search quests. Please try again.")
            await interaction.followup.send(embed=embed, ephemeral=False)

    @app_commands.command(name="deletequest", description="Delete a quest (Admin only)")
    @app_commands.describe(quest_id="The ID of the quest to delete")
    async def delete_quest_command(self, interaction: discord.Interaction, quest_id: str):
        """Delete a quest - Admin only command"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            embed = create_error_embed(
                "Permission Denied",
                "Only administrators can delete quests."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Get quest details before deletion
        quest = await self.quest_manager.get_quest(quest_id)
        if not quest:
            embed = create_error_embed(
                "Quest Not Found", 
                f"No quest found with ID: `{quest_id}`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if quest belongs to this guild
        if quest.guild_id != interaction.guild.id:
            embed = create_error_embed(
                "Quest Not Found", 
                "No quest found with that ID in this server."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Attempt to delete the quest
        success = await self.quest_manager.delete_quest(quest_id)
        
        if success:
            embed = create_success_embed(
                "Quest Deleted Successfully",
                f"Quest **{quest.title}** has been permanently deleted.",
                f"Quest ID: `{quest_id}`\nAll associated progress has been removed."
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            embed = create_error_embed(
                "Deletion Failed",
                "Failed to delete the quest. Please try again."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="quest_info", description="Get detailed information about a specific quest")
    @app_commands.describe(quest_id="The ID of the quest")
    async def quest_info(self, interaction: discord.Interaction, quest_id: str):
        """Get detailed information about a specific quest"""
        quest = await self.quest_manager.get_quest(quest_id)
        
        if not quest or quest.guild_id != interaction.guild.id:
            embed = create_error_embed("Quest Not Found", "No quest found with that ID in this server.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        # Check if this is a team quest
        team_info = None
        if self.team_quest_manager:
            team_info = await self.team_quest_manager.get_team_status(quest_id)

        embed = create_quest_embed(quest, team_info=team_info)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="my_quests", description="View your quest progress")
    async def my_quests(self, interaction: discord.Interaction):
        """View user's quest progress"""
        user_quests = await self.quest_manager.get_user_quests(interaction.user.id, interaction.guild.id)
        
        if not user_quests:
            embed = create_info_embed(
                "No Quest Activity",
                "You haven't accepted any quests yet.",
                "Start your adventure by exploring available quests with /list_quests"
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        # Create quest progress embed with standard styling
        embed = create_info_embed(
            "My Quest Progress",
            f"Quest overview for {interaction.user.display_name}"
        )

        # Group by status
        status_groups = {}
        for progress in user_quests:
            status = progress.status
            if status not in status_groups:
                status_groups[status] = []
            status_groups[status].append(progress)

        # Display assigned starter quests (ready to submit directly)
        if 'assigned' in status_groups:
            assigned_quests = status_groups['assigned']
            quest_list = []
            
            for progress in assigned_quests[:5]:  # Show up to 5 starter quests
                quest = await self.quest_manager.get_quest(progress.quest_id)
                if quest:
                    quest_list.append(f"▸ **{quest.title}** (ID: `{quest.quest_id}`) - 📝 Ready to submit! Use `/submit_quest {quest.quest_id}`")
            
            embed.add_field(
                name="🎯 Starter Quests (Auto-Assigned)",
                value=f"**Total**: {len(assigned_quests)} quests\n\n" + "\n".join(quest_list),
                inline=False
            )

        # Display accepted missions 
        if 'accepted' in status_groups:
            accepted_quests = status_groups['accepted']
            quest_list = []
            
            for progress in accepted_quests[:5]:  # Show up to 5 quests
                quest = await self.quest_manager.get_quest(progress.quest_id)
                if quest:
                    quest_list.append(f"▸ **{quest.title}** (ID: `{quest.quest_id}`) - 📝 Use `/submit_quest {quest.quest_id}` to complete")
            
            embed.add_field(
                name="■ Active Quests",
                value=f"**Total**: {len(accepted_quests)} quests\n\n" + "\n".join(quest_list),
                inline=False
            )

        # Display approved missions 
        if 'approved' in status_groups:
            approved_quests = status_groups['approved']
            quest_list = []
            
            for progress in approved_quests[:5]:  # Show up to 5 quests
                quest = await self.quest_manager.get_quest(progress.quest_id)
                if quest:
                    # Mark starter quests as one-time completed
                    if quest.quest_id.startswith('starter'):
                        quest_list.append(f"▸ **{quest.title}** (ID: `{quest.quest_id}`) - *One-time completion*")
                    else:
                        quest_list.append(f"▸ **{quest.title}** (ID: `{quest.quest_id}`)")
            
            embed.add_field(
                name="■ Completed Quests",
                value=f"**Total**: {len(approved_quests)} quests\n\n" + "\n".join(quest_list),
                inline=False
            )

        # Performance metrics
        stats = await self.user_stats_manager.get_user_stats(interaction.user.id, interaction.guild.id)
        if stats:
            success_rate = (stats.quests_completed / stats.quests_accepted * 100) if stats.quests_accepted > 0 else 0
            
            # Get user's leaderboard rank and points
            user_data = await self.leaderboard_manager.get_user_stats(interaction.guild.id, interaction.user.id)
            current_points = user_data['points'] if user_data else 0
            current_rank = get_rank_title_by_points(current_points, interaction.user)
            
            embed.add_field(
                name="■ Quest Statistics",
                value=f"**Completed**: {stats.quests_completed}\n**Success Rate**: {success_rate:.1f}%\n**Points**: {current_points}",
                inline=True
            )
            
            embed.add_field(
                name="■ Current Status",
                value=f"**Rank**: {current_rank}\n**Active Quests**: {len(status_groups.get('accepted', []))}\n**Standing**: Good",
                inline=True
            )

        # Create interactive view for quest management
        view = InteractiveMyQuestsView(user_quests, self.quest_manager, interaction.user.id, interaction.guild.id)
        
        embed.set_footer(text="Use the buttons below to manage your quest progress")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)

    

    @app_commands.command(name="submit_quest", description="Submit proof for a completed quest")
    @app_commands.describe(
        quest_id="The quest ID to submit",
        proof_text="Description of your proof",
        proof_image1="Image proof 1",
        proof_image2="Image proof 2",
        proof_image3="Image proof 3",
        proof_image4="Image proof 4",
        proof_image5="Image proof 5",
        proof_image6="Image proof 6",
        proof_image7="Image proof 7",
        proof_image8="Image proof 8",
        proof_image9="Image proof 9",
        proof_image10="Image proof 10",
        proof_image11="Image proof 11",
        proof_image12="Image proof 12",
        proof_image13="Image proof 13",
        proof_image14="Image proof 14",
        proof_image15="Image proof 15",
        proof_image16="Image proof 16",
        proof_image17="Image proof 17",
        proof_image18="Image proof 18",
        proof_image19="Image proof 19",
        proof_image20="Image proof 20"
    )
    async def submit_quest(self, interaction: discord.Interaction, 
                          quest_id: str, 
                          proof_text: str,
                          proof_image1: discord.Attachment = None,
                          proof_image2: discord.Attachment = None,
                          proof_image3: discord.Attachment = None,
                          proof_image4: discord.Attachment = None,
                          proof_image5: discord.Attachment = None,
                          proof_image6: discord.Attachment = None,
                          proof_image7: discord.Attachment = None,
                          proof_image8: discord.Attachment = None,
                          proof_image9: discord.Attachment = None,
                          proof_image10: discord.Attachment = None,
                          proof_image11: discord.Attachment = None,
                          proof_image12: discord.Attachment = None,
                          proof_image13: discord.Attachment = None,
                          proof_image14: discord.Attachment = None,
                          proof_image15: discord.Attachment = None,
                          proof_image16: discord.Attachment = None,
                          proof_image17: discord.Attachment = None,
                          proof_image18: discord.Attachment = None,
                          proof_image19: discord.Attachment = None,
                          proof_image20: discord.Attachment = None):
        """Submit proof for a completed quest"""
        # Defer response immediately to prevent timeout
        await interaction.response.defer(ephemeral=False)
        
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.followup.send(embed=embed)
            return
        
        try:
            # Collect all proof images
            proof_images = [
                proof_image1, proof_image2, proof_image3, proof_image4, proof_image5,
                proof_image6, proof_image7, proof_image8, proof_image9, proof_image10,
                proof_image11, proof_image12, proof_image13, proof_image14, proof_image15,
                proof_image16, proof_image17, proof_image18, proof_image19, proof_image20
            ]
            image_urls = []
            
            for image in proof_images:
                if image:
                    image_urls.append(image.url)

            # Check if this is a team quest first
            team = None
            if self.team_quest_manager:
                team = await self.team_quest_manager.get_team_status(quest_id)
            
            if team and team.team_members:
                # This is a team quest - check if user is a team member
                if interaction.user.id not in team.team_members:
                    embed = create_error_embed(
                        "Submission Failed",
                        "You are not a member of the team for this quest. Use `/join_team` to join first."
                    )
                    await interaction.followup.send(embed=embed, ephemeral=False)
                    return
                    
                # For team quests, we need to create a quest progress entry if it doesn't exist
                progress = await self.quest_manager.database.get_user_quest_progress(interaction.user.id, quest_id)
                if not progress:
                    # Create a progress entry for team member submission
                    from bot.models import QuestProgress, ProgressStatus
                    from datetime import datetime
                    progress = QuestProgress(
                        quest_id=quest_id,
                        user_id=interaction.user.id,
                        guild_id=interaction.guild.id,
                        status=ProgressStatus.ACCEPTED,
                        accepted_at=datetime.now(),
                        channel_id=interaction.channel.id
                    )
                    await self.quest_manager.database.save_quest_progress(progress)
                
                # Now complete the quest
                progress = await self.quest_manager.complete_quest(
                    quest_id, interaction.user.id, proof_text, image_urls
                )
            else:
                # Regular individual quest
                progress = await self.quest_manager.complete_quest(
                    quest_id, interaction.user.id, proof_text, image_urls
                )

            if not progress:
                embed = create_error_embed(
                    "Submission Failed",
                    "You haven't accepted this quest or it's already submitted."
                )
                await interaction.followup.send(embed=embed, ephemeral=False)
                return

            quest = await self.quest_manager.get_quest(quest_id)
            quest_title = quest.title if quest else "Unknown Quest"
            embed = create_success_embed(
                "Quest Submitted!",
                f"Your proof for **{quest_title}** has been submitted for review.",
                f"Quest ID: `{quest_id}`\nProof: {truncate_text(proof_text, 500)}\nImages: {len(image_urls)} attached (up to 20 supported)"
            )

            if image_urls:
                embed.set_image(url=image_urls[0])

            await interaction.followup.send(embed=embed, ephemeral=False)

            # Notify approval channel
            approval_channel_id = await self.channel_config.get_quest_approval_channel(interaction.guild.id)
            if approval_channel_id:
                approval_channel = self.bot.get_channel(approval_channel_id)
                if approval_channel:
                    approval_embed = discord.Embed(
                        title="QUEST SUBMISSION | PENDING APPROVAL",
                        color=Colors.WARNING,
                        timestamp=discord.utils.utcnow()
                    )
                    approval_embed.description = f"**{quest_title}** requires administrative review"
                    
                    # Quest details section
                    quest_rank = str(quest.rank).title() if quest and quest.rank else 'Unknown'
                    quest_details = f"**Quest ID:** `{quest_id}`\n**Title:** {quest_title}\n**Rank:** {quest_rank}"
                    approval_embed.add_field(
                        name="▬ QUEST DETAILS", 
                        value=quest_details, 
                        inline=True
                    )
                    
                    # Submitter information
                    submitter_info = f"**User:** {interaction.user.mention}\n**Display Name:** {interaction.user.display_name}\n**User ID:** {interaction.user.id}"
                    approval_embed.add_field(
                        name="▬ SUBMITTED BY", 
                        value=submitter_info, 
                        inline=True
                    )
                    
                    # Empty field for spacing
                    approval_embed.add_field(name="\u200b", value="\u200b", inline=True)
                    
                    # Proof section
                    approval_embed.add_field(
                        name="▬ PROOF SUBMITTED", 
                        value=f"**{truncate_text(proof_text, 800)}**", 
                        inline=False
                    )
                    
                    if image_urls:
                        approval_embed.set_image(url=image_urls[0])
                        if len(image_urls) > 1:
                            approval_embed.add_field(
                                name="▬ ATTACHMENTS", 
                                value=f"**{len(image_urls)}** images submitted (first image displayed above)", 
                                inline=False
                            )
                    
                    await approval_channel.send(embed=approval_embed)
                    
                    # Send additional images if more than 1 submitted (limit to prevent API issues)
                    if len(image_urls) > 1:
                        additional_images = image_urls[1:6]  # Limit to 5 additional images max
                        for i, image_url in enumerate(additional_images, 2):
                            try:
                                additional_embed = create_info_embed(
                                    f"ADDITIONAL PROOF IMAGE {i}/{min(len(image_urls), 6)}",
                                    f"**Quest:** {quest_title}\n**Submitted by:** {interaction.user.display_name}",
                                    "Additional evidence for quest completion verification"
                                )
                                additional_embed.set_image(url=image_url)
                                await approval_channel.send(embed=additional_embed)
                                await asyncio.sleep(0.5)  # Small delay to prevent rate limiting
                            except discord.HTTPException as e:
                                logger.warning(f"⚠️ Failed to send additional quest image {i}: {e}")
                                break  # Stop sending more images if we hit API limits
                    
                    # Add approval instructions
                    approval_embed.add_field(
                        name="▬ ADMIN ACTIONS",
                        value=f"Use `/approve_quest {quest_id} @{interaction.user.display_name}` to approve\nUse `/reject_quest {quest_id} @{interaction.user.display_name}` to reject",
                        inline=False
                    )
                    
                    approval_embed.set_footer(text="HEAVENLY DEMON SECT • QUEST APPROVAL SYSTEM")
            
        except Exception as e:
            logger.error(f"❌ Error in submit_quest: {e}")
            embed = create_error_embed("System Error", "An unexpected error occurred while submitting. Please try again.")
            try:
                await interaction.followup.send(embed=embed, ephemeral=False)
            except:
                logger.error(f"❌ Failed to send error message for submit_quest: {e}")

    @app_commands.command(name="approve_quest", description="Approve a completed quest")
    @app_commands.describe(
        quest_id="The quest ID to approve",
        user="The user who completed the quest",
        points="Points to award (optional, overrides automatic reward calculation)"
    )
    async def approve_quest(self, interaction: discord.Interaction, 
                           quest_id: str, user: discord.Member, points: int = None):
        """Approve a completed quest and award points"""
        # Defer response immediately to prevent timeout
        await interaction.response.defer(ephemeral=False)
        
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.followup.send(embed=embed)
            return
        
        if not has_quest_creation_permission(interaction.user, interaction.guild):
            await interaction.followup.send("You don't have permission to approve quests!", ephemeral=False)
            return

        progress = await self.quest_manager.approve_quest(quest_id, user.id, interaction.user.id)
        if not progress:
            embed = create_error_embed(
                "Approval Failed",
                "Quest not found or not ready for approval."
            )
            await interaction.followup.send(embed=embed, ephemeral=False)
            return

        quest = await self.quest_manager.get_quest(quest_id)
        quest_title = quest.title if quest else "Unknown Quest"
        quest_reward = quest.reward if quest else None
        
        # Award points - use provided points or extract from reward
        if points is not None:
            award_points = points
            points_source = "Manual Override"
        else:
            award_points = self._extract_points_from_reward(quest_reward)
            points_source = "Auto-extracted from Reward"
        
        if award_points > 0:
            # Check if this is a team quest
            team = None
            if self.team_quest_manager:
                team = await self.team_quest_manager.get_team_status(quest_id)
            
            if team and team.team_members:
                # Team quest - award points to all team members
                awarded_members = []
                for member_id in team.team_members:
                    try:
                        member = interaction.guild.get_member(member_id)
                        if member:
                            await self.leaderboard_manager.award_quest_points(
                                interaction.guild.id, member_id, member.display_name, award_points, quest_id
                            )
                            await self.user_stats_manager.update_quest_completed(member_id, interaction.guild.id)
                            awarded_members.append(member.display_name)
                    except Exception as e:
                        logger.error(f"Failed to award points to team member {member_id}: {e}")
                
                # Update points source to indicate team distribution
                points_source += f" (Team: {len(awarded_members)} members)"
            else:
                # Regular quest - award points to single user
                await self.leaderboard_manager.award_quest_points(
                    interaction.guild.id, user.id, user.display_name, award_points, quest_id
                )
                # Update user stats
                await self.user_stats_manager.update_quest_completed(user.id, interaction.guild.id)
        
        # Auto-update all active leaderboard views to show new points immediately
        await update_active_leaderboards(interaction.guild.id)

        # Disband team automatically after successful team quest approval
        if team and team.team_members and len(team.team_members) > 1:
            try:
                await self.team_quest_manager._disband_team(quest_id)
                logger.info(f"✅ Automatically disbanded team for completed quest {quest_id}")
            except Exception as e:
                logger.error(f"❌ Failed to disband team for quest {quest_id}: {e}")

        # Create enhanced approval embed with team information
        if team and team.team_members and len(team.team_members) > 1:
            description = f"**{quest_title}** has been approved for the entire team."
            additional_info = f"**Score Awarded:** {award_points} per member\n**Source:** {points_source}\n**Team Size:** {len(team.team_members)} members"
        else:
            description = f"{quest_title} has been approved for {user.display_name}."
            additional_info = f"Score Awarded: {award_points}\n**Source:** {points_source}"
        
        embed = create_success_embed(
            "Quest Approved!",
            description,
            additional_info
        )
        
        # Add quest details
        embed.add_field(
            name="Quest Details",
            value=f"**ID:** `{quest_id}`\n**Reward:** {quest_reward or 'No reward specified'}",
            inline=True
        )
        
        embed.add_field(
            name="Approved by",
            value=interaction.user.mention,
            inline=True
        )

        await interaction.followup.send(embed=embed, ephemeral=False)

        # Send notifications to users who completed the quest
        try:
            if team and team.team_members and len(team.team_members) > 1:
                # Team quest - notify all team members
                for member_id in team.team_members:
                    try:
                        member = interaction.guild.get_member(member_id)
                        if member:
                            team_notification_embed = create_success_embed(
                                "Team Quest Approved!",
                                f"Your team quest **{quest_title}** has been approved!",
                                f"**Score Awarded:** {award_points} points per member\n**Quest ID:** `{quest_id}`\n**Team Size:** {len(team.team_members)} members\n**Approved by:** {interaction.user.display_name}"
                            )
                            
                            # Try to send DM first, fallback to channel mention if DM fails
                            try:
                                await member.send(embed=team_notification_embed)
                                logger.info(f"✅ Sent DM notification to team member {member.display_name} for approved quest {quest_id}")
                            except (discord.Forbidden, discord.HTTPException):
                                # DM failed for this member, add to fallback list
                                logger.debug(f"DM failed for team member {member.display_name}, will use channel mention")
                    except Exception as e:
                        logger.error(f"❌ Failed to notify team member {member_id}: {e}")
                
                # Note: Team completion notification will be sent to quest accept channel below
                # (removing duplicate team notification to wrong channel)
                logger.info(f"✅ Sent individual DM notifications to team members for approved quest {quest_id}")
            else:
                # Individual quest - notify single user
                user_notification_embed = create_success_embed(
                    "Quest Approved!",
                    f"Your quest **{quest_title}** has been approved!",
                    f"**Score Awarded:** {award_points} points\n**Quest ID:** `{quest_id}`\n**Approved by:** {interaction.user.display_name}"
                )
                
                # Try to send DM first, fallback to channel mention if DM fails
                try:
                    await user.send(embed=user_notification_embed)
                    logger.info(f"✅ Sent DM notification to {user.display_name} for approved quest {quest_id}")
                except (discord.Forbidden, discord.HTTPException):
                    # DM failed, send mention in notification channel instead
                    notification_channel_id = await self.channel_config.get_notification_channel(interaction.guild.id)
                    notification_channel = None
                    
                    if notification_channel_id:
                        notification_channel = self.bot.get_channel(notification_channel_id)
                    
                    # If no notification channel configured, use current channel
                    if not notification_channel:
                        notification_channel = interaction.channel
                    
                    mention_embed = create_success_embed(
                        "Quest Approved!",
                        f"{user.display_name} Your quest **{quest_title}** has been approved!",
                        f"**Score Awarded:** {award_points} points\n**Quest ID:** `{quest_id}`\n**Approved by:** {interaction.user.display_name}"
                    )
                    
                    await notification_channel.send(embed=mention_embed)
                    logger.info(f"✅ Sent channel notification to {user.display_name} for approved quest {quest_id}")
                
        except Exception as e:
            logger.error(f"❌ Failed to send user notifications for approved quest: {e}")

        # Also send notification to quest accept channel
        try:
            accept_channel_id = await self.channel_config.get_quest_accept_channel(interaction.guild.id)
            if accept_channel_id:
                accept_channel = self.bot.get_channel(accept_channel_id)
                if accept_channel:
                    if team and team.team_members and len(team.team_members) > 1:
                        # Team quest accept channel notification
                        member_names = []
                        for member_id in team.team_members:
                            member = interaction.guild.get_member(member_id)
                            if member:
                                member_names.append(member.display_name)
                        
                        accept_embed = create_success_embed(
                            "Team Quest Completed!",
                            f"Team quest **{quest_title}** has been successfully completed and approved!",
                            f"**Team Members:** {', '.join(member_names)}\n**Score Awarded:** {award_points} points per member\n**Quest ID:** `{quest_id}`\n**Approved by:** {interaction.user.display_name}"
                        )
                    else:
                        # Individual quest accept channel notification
                        accept_embed = create_success_embed(
                            "Quest Completed!",
                            f"{user.display_name} has successfully completed **{quest_title}**!",
                            f"**Score Awarded:** {award_points} points\n**Quest ID:** `{quest_id}`\n**Approved by:** {interaction.user.display_name}"
                        )
                    
                    await accept_channel.send(embed=accept_embed)
                    logger.info(f"✅ Sent quest completion notification to accept channel for quest {quest_id}")
        except Exception as e:
            logger.error(f"❌ Failed to send accept channel notification: {e}")

        # Check for rank promotion
        if award_points > 0:
            await self._check_rank_promotion(user, interaction.guild.id, interaction.channel)
            
        # Check welcome automation - if user completed starter quest, trigger role reward
        if hasattr(self.bot, 'welcome_manager') and self.bot.welcome_manager:
            try:
                await self.bot.welcome_manager.check_quest_completion(user.id, interaction.guild.id, quest_id, self.bot)
            except Exception as e:
                logger.error(f"❌ Error checking welcome quest completion: {e}")

    def _extract_points_from_reward(self, reward_text) -> int:
        """Extract point value from reward text - simple digit format"""
        import re
        
        if not reward_text:
            return 10  # Default points if no reward text
        
        # Simple patterns focusing on digits with descriptions
        patterns = [
            # Numbers at start: "50 - special reward", "100 collector badge"
            r'^(\d+)\s*[-–—\s]',
            # Numbers in brackets: "[50]", "(100)"
            r'[\[\(](\d+)[\]\)]',
            # Reward format: "Reward: 50", "50:"
            r'(\d+)\s*:',
            # Just find the first number in the text
            r'(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, reward_text.strip())
            if match:
                points = int(match.group(1))
                # Reasonable bounds check
                if 1 <= points <= 10000:
                    return points
        
        return 10  # Default points if nothing found

    async def _check_rank_promotion(self, member: discord.Member, guild_id: int, channel):
        """Check if user got promoted and send congratulations"""
        try:
            user_stats = await self.leaderboard_manager.get_user_stats(guild_id, member.id)
            if user_stats:
                current_points = user_stats['points']
                old_rank = get_rank_title_by_points(current_points - 10, member)  # Estimate old rank
                new_rank = get_rank_title_by_points(current_points, member)
                
                if old_rank != new_rank:
                    embed = create_promotion_embed(member, old_rank, new_rank, current_points)
                    await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Error checking rank promotion: {e}")

    @app_commands.command(name="test_reward", description="Test how many points would be extracted from reward text")
    @app_commands.describe(reward_text="Reward text to test")
    async def test_reward(self, interaction: discord.Interaction, reward_text: str):
        """Test point extraction from reward text"""
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        if not has_quest_creation_permission(interaction.user, interaction.guild):
            await interaction.response.send_message("You don't have permission to use this command!", ephemeral=False)
            return
            
        extracted_points = self._extract_points_from_reward(reward_text)
        
        embed = create_info_embed(
            "Reward Score Extraction Test",
            f"**Input:** {reward_text}\n**Extracted Score:** {extracted_points}",
            "This shows how much score would be automatically awarded when approving a quest with this reward."
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # LEADERBOARD COMMANDS
    @app_commands.command(name="leaderboard", description="Show the server leaderboard")
    @app_commands.describe(page="Page number to view")
    async def leaderboard(self, interaction: discord.Interaction, page: int = 1):
        """Display server leaderboard with pagination"""
        try:
            # Defer the response immediately to prevent timeout
            await interaction.response.defer(ephemeral=False)
            
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.followup.send(embed=embed)
                return
            
            view = LeaderboardView(interaction.guild.id, self.leaderboard_manager)
            view.current_page = max(1, page)
            
            # Fetch initial data
            success = await view.fetch_leaderboard_data()
            if not success:
                embed = create_error_embed(
                    "Leaderboard Error",
                    "Failed to load leaderboard data. Please try again later."
                )
                await interaction.followup.send(embed=embed)
                return

            # Create embed
            guild_name = interaction.guild.name
            embed = create_leaderboard_embed(
                view.leaderboard_data,
                view.current_page,
                view.total_pages,
                guild_name,
                interaction.guild,
                view.total_guild_points
            )

            # Update button states
            view.update_button_states()

            # Send response using followup since we deferred
            message = await interaction.followup.send(embed=embed, view=view)
            
            # Store message reference for auto-updates
            view.message = message

        except Exception as e:
            logger.error(f"❌ Error in leaderboard command: {e}")
            embed = create_error_embed(
                "Command Error",
                "An error occurred while displaying the leaderboard."
            )
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=False)
            except Exception as followup_error:
                logger.error(f"❌ Failed to send error response: {followup_error}")

    @app_commands.command(name="mystats", description="View your personal statistics")
    async def mystats(self, interaction: discord.Interaction):
        """Show user's personal statistics"""
        try:
            user_data = await self.leaderboard_manager.get_user_stats(interaction.guild.id, interaction.user.id)
            
            if not user_data:
                embed = create_error_embed(
                    "No Stats Found",
                    "You don't have any statistics yet. Start participating to build your profile!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return

            embed = create_user_stats_embed(interaction.user, user_data, interaction.guild.name)
            await interaction.response.send_message(embed=embed, ephemeral=False)

        except Exception as e:
            logger.error(f"❌ Error getting user stats: {e}")
            embed = create_error_embed(
                "Error",
                "Failed to retrieve your statistics. Please try again later."
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="test_notification", description="Test notification system (Admin only)")
    @app_commands.describe(
        user="The user to test notification for",
        notification_type="Type of notification to test"
    )
    @app_commands.choices(notification_type=[
        app_commands.Choice(name="promotion", value="promotion"),
        app_commands.Choice(name="retirement", value="retirement")
    ])
    @app_commands.default_permissions(administrator=True)
    async def test_notification(self, interaction: discord.Interaction, user: discord.Member, notification_type: str):
        """Test notification system"""
        try:
            if notification_type == "promotion":
                # Import needed functions
                from bot.events import send_promotion_congratulations
                await send_promotion_congratulations(user, "Test Rank", 100, None, self.bot)
                
                embed = create_success_embed(
                    "Test Notification Sent",
                    f"Sent test promotion notification for {user.display_name}"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
            elif notification_type == "retirement":
                # Import needed functions  
                from bot.events import send_retirement_notification
                await send_retirement_notification(user, None, "Test Rank", self.bot)
                
                embed = create_success_embed(
                    "Test Notification Sent", 
                    f"Sent test retirement notification for {user.display_name}"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                
        except Exception as e:
            logger.error(f"❌ Error testing notification: {e}")
            embed = create_error_embed("Test Failed", f"Error: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="addpoints", description="Add points to a user (Admin only)")
    @app_commands.describe(
        user="The user to give points to",
        points="Number of points to add"
    )
    @app_commands.default_permissions(administrator=True)
    async def add_points(self, interaction: discord.Interaction, user: discord.Member, points: int):
        """Add points to a user"""
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        if user.bot:
            embed = create_error_embed("Invalid Target", "Cannot add points to bots.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        success = await self.leaderboard_manager.update_points(
            interaction.guild.id, user.id, points, user.display_name
        )

        if success:
            embed = create_success_embed(
                "Points Added",
                f"Successfully added {points} points to {user.display_name}."
            )
            await interaction.response.send_message(embed=embed)
            
            # Auto-update all active leaderboard views to show new points immediately
            await update_active_leaderboards(interaction.guild.id)
            
            # Check for rank promotion
            await self._check_rank_promotion(user, interaction.guild.id, interaction.channel)
        else:
            embed = create_error_embed(
                "Failed to Add Points",
                "An error occurred while adding points. Please try again."
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="setpoints", description="Set user's points to a specific value (Admin only)")
    @app_commands.describe(
        user="The user to set points for",
        points="Number of points to set"
    )
    @app_commands.default_permissions(administrator=True)
    async def set_points(self, interaction: discord.Interaction, user: discord.Member, points: int):
        """Set user's points to a specific value"""
        # Safety check for guild
        if not interaction.guild:
            embed = create_error_embed("Server Error", "This command must be used in a server.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        if user.bot:
            embed = create_error_embed("Invalid Target", "Cannot set points for bots.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return

        # Get current points
        current_stats = await self.leaderboard_manager.get_user_stats(interaction.guild.id, user.id)
        current_points = current_stats['points'] if current_stats else 0
        
        # Calculate difference and update
        difference = points - current_points
        success = await self.leaderboard_manager.update_points(
            interaction.guild.id, user.id, difference, user.display_name
        )

        if success:
            embed = create_success_embed(
                "Points Set",
                f"Successfully set {user.display_name}'s points to {points}."
            )
            await interaction.response.send_message(embed=embed)
            
            # Auto-update all active leaderboard views to show new points immediately
            await update_active_leaderboards(interaction.guild.id)
        else:
            embed = create_error_embed(
                "Failed to Set Points",
                "An error occurred while setting points. Please try again."
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)

    # TEAM QUEST COMMANDS

    @app_commands.command(name="join_team", description="Join an existing team for a quest")
    @app_commands.describe(quest_id="The quest ID to join a team for")
    async def join_team(self, interaction: discord.Interaction, quest_id: str):
        """Join an existing team for a quest"""
        if not self.team_quest_manager:
            embed = create_error_embed("Feature Unavailable", "Team quests are not enabled.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        success, message = await self.team_quest_manager.join_team(
            quest_id, interaction.user.id, interaction.guild.id
        )
        
        if success:
            quest = await self.quest_manager.get_quest(quest_id)
            team = await self.team_quest_manager.get_team_status(quest_id)
            
            embed = create_success_embed(
                "Joined Team!",
                f"Successfully joined the team for quest **{quest.title if quest else 'Unknown Quest'}**",
                f"**Team Members:** {len(team.team_members)}/{team.team_size_required}\n**Team Complete:** {'Yes' if team.is_team_complete else 'No'}\n**Quest ID:** `{quest_id}`"
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            embed = create_error_embed("Join Failed", message)
            await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="leave_team", description="Leave your current team for a quest")
    @app_commands.describe(quest_id="The quest ID to leave the team for")
    async def leave_team(self, interaction: discord.Interaction, quest_id: str):
        """Leave a team quest"""
        if not self.team_quest_manager:
            embed = create_error_embed("Feature Unavailable", "Team quests are not enabled.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        success, message = await self.team_quest_manager.leave_team(
            quest_id, interaction.user.id, interaction.guild.id
        )
        
        if success:
            embed = create_success_embed("Left Team", message)
            await interaction.response.send_message(embed=embed, ephemeral=False)
        else:
            embed = create_error_embed("Leave Failed", message)
            await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="team_status", description="View team status for a quest")
    @app_commands.describe(quest_id="The quest ID to check team status for")
    async def team_status(self, interaction: discord.Interaction, quest_id: str):
        """View team status for a quest"""
        if not self.team_quest_manager:
            embed = create_error_embed("Feature Unavailable", "Team quests are not enabled.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        team = await self.team_quest_manager.get_team_status(quest_id)
        if not team:
            embed = create_error_embed("No Team Found", f"No team exists for quest ID: {quest_id}")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        quest = await self.quest_manager.get_quest(quest_id)
        quest_title = quest.title if quest else "Unknown Quest"
        
        # Get member names
        member_names = []
        for member_id in team.team_members:
            member = interaction.guild.get_member(member_id)
            if member:
                role = "Leader" if member_id == team.team_leader else "Member"
                member_names.append(f"▸ **{role}:** {member.display_name}")
            else:
                role = "Leader" if member_id == team.team_leader else "Member"
                member_names.append(f"▸ **{role}:** <@{member_id}>")
        
        # Prepare fields for standardized embed
        status = "Complete" if team.is_team_complete else "Recruiting"
        created_date = team.team_formed_at.strftime('%B %d, %Y') if team.team_formed_at else 'Unknown'
        
        fields = [
            {
                "name": "━━━━━━━━━ Team Progress ━━━━━━━━━",
                "value": f"▸ **Size:** {len(team.team_members)}/{team.team_size_required}\n▸ **Status:** {status}\n▸ **Created:** {created_date}",
                "inline": False
            }
        ]
        
        if member_names:
            fields.append({
                "name": "━━━━━━━━━ Team Members ━━━━━━━━━",
                "value": "\n".join(member_names[:10]),  # Limit to 10 for display
                "inline": False
            })
        
        # Use success or warning embed based on team completion status
        if team.is_team_complete:
            embed = create_success_embed(
                "Team Status",
                f"Quest: {quest_title}",
                f"Team quest ID: `{quest_id}`",
                fields
            )
        else:
            embed = create_info_embed(
                "Team Status", 
                f"Quest: {quest_title}",
                f"Team quest ID: `{quest_id}`",
                fields
            )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="my_teams", description="View all teams you're part of")
    async def my_teams(self, interaction: discord.Interaction):
        """View all teams the user is part of"""
        if not self.team_quest_manager:
            embed = create_error_embed("Feature Unavailable", "Team quests are not enabled.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        user_teams = await self.team_quest_manager.get_user_teams(interaction.user.id, interaction.guild.id)
        
        if not user_teams:
            embed = create_info_embed(
                "No Teams",
                "You're not currently part of any teams.",
                "Use `/create_team` to start a team or `/join_team` to join an existing one!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        # Prepare team data for standardized embed
        team_fields = []
        
        for i, quest_id in enumerate(user_teams[:10], 1):  # Limit to 10 teams
            team = await self.team_quest_manager.get_team_status(quest_id)
            quest = await self.quest_manager.get_quest(quest_id)
            
            if team and quest:
                role = "Leader" if team.team_leader == interaction.user.id else "Member"
                status = "Complete" if team.is_team_complete else "Recruiting"
                
                team_fields.append({
                    "name": f"━━━━━━━━━ {quest.title} ━━━━━━━━━",
                    "value": f"▸ **Role:** {role}\n▸ **Status:** {status}\n▸ **Size:** {len(team.team_members)}/{team.team_size_required}\n▸ **Quest ID:** `{quest_id}`",
                    "inline": False
                })
        
        embed = create_info_embed(
            "My Teams",
            f"Team overview for {interaction.user.display_name}",
            "Your current and active team quest participation",
            team_fields
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="available_teams", description="View all teams looking for members")
    async def available_teams(self, interaction: discord.Interaction):
        """View all teams that need more members"""
        if not self.team_quest_manager:
            embed = create_error_embed("Feature Unavailable", "Team quests are not enabled.")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        available_teams = await self.team_quest_manager.get_available_teams(interaction.guild.id)
        
        if not available_teams:
            embed = create_info_embed(
                "No Teams Available",
                "There are currently no teams looking for members.",
                "Use `/create_team` to start your own team!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
            return
        
        # Prepare available team data for standardized embed
        team_fields = []
        
        for i, team in enumerate(available_teams[:10], 1):  # Limit to 10 teams
            quest = await self.quest_manager.get_quest(team.quest_id)
            quest_title = quest.title if quest else "Unknown Quest"
            
            leader = interaction.guild.get_member(team.team_leader)
            leader_name = leader.display_name if leader else "Unknown"
            
            team_fields.append({
                "name": f"━━━━━━━━━ {quest_title} ━━━━━━━━━",
                "value": f"▸ **Leader:** {leader_name}\n▸ **Size:** {len(team.team_members)}/{team.team_size_required}\n▸ **Join:** `/join_team {team.quest_id}`",
                "inline": False
            })
        
        embed = create_success_embed(
            "Teams Looking for Members",
            "Available teams you can join for collaborative quests",
            "Join a team to participate in group missions and earn shared rewards",
            team_fields
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ========================================
    # RANK PROMOTION COMMANDS
    # ========================================

    @app_commands.command(name="getrank", description="Request promotion to a specific rank")
    @app_commands.describe(
        rank="The rank you want to be promoted to",
        username="Your username (text)",
        image="Upload an image (required)"
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
    async def getrank(self, interaction: discord.Interaction, rank: str, username: str, image: discord.Attachment):
        """Submit a rank request for approval with enhanced requirements validation"""
        try:
            # Import role requirements from utils.py
            from bot.utils import ROLE_REQUIREMENTS, SPECIAL_ROLES, ENHANCED_RANK_REQUIREMENTS
            from bot.rank_validator import RankValidator
            
            # Convert rank string to role ID
            try:
                role_id = int(rank)
            except ValueError:
                embed = create_error_embed("Invalid Rank", "The selected rank is not valid.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            if role_id not in ENHANCED_RANK_REQUIREMENTS:
                embed = create_error_embed("Invalid Rank", "The selected rank is not available for promotion.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Find the target Discord role
            target_role = interaction.guild.get_role(role_id)
            if not target_role:
                embed = create_error_embed(
                    "Role Not Found", 
                    f"The Discord role with ID {role_id} was not found on this server. Please contact an admin."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Check if user already has this specific role
            if target_role in interaction.user.roles:
                embed = create_info_embed(
                    "Already Have This Rank",
                    f"You already have the '{target_role.name}' role!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get rank request channel
            rank_request_channel_id = await self.channel_config.get_rank_request_channel(interaction.guild.id)
            if not rank_request_channel_id:
                embed = create_error_embed(
                    "Channel Not Configured", 
                    "Rank request channel has not been set up. Please contact an admin to configure it using `/setup_channels`."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            rank_request_channel = interaction.guild.get_channel(rank_request_channel_id)
            if not rank_request_channel:
                embed = create_error_embed(
                    "Channel Not Found", 
                    "The configured rank request channel no longer exists. Please contact an admin."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Get user's current points for display
            user_data = await self.leaderboard_manager.get_user_stats(interaction.guild.id, interaction.user.id)
            current_points = user_data.get('points', 0) if user_data else 0
            
            # Enhanced validation using the new rank validator
            rank_validator = RankValidator(self.quest_manager.database)
            member_role_ids = [role.id for role in interaction.user.roles]
            
            is_valid, validation_errors = await rank_validator.validate_rank_requirements(
                interaction.user.id, interaction.guild.id, role_id, member_role_ids, current_points
            )
            
            # If validation fails, show detailed requirements
            if not is_valid:
                progress_summary = await rank_validator.get_rank_progress_summary(
                    interaction.user.id, interaction.guild.id, role_id, member_role_ids, current_points
                )
                
                embed = create_error_embed(
                    "Requirements Not Met",
                    f"You don't meet the requirements for **{target_role.name}**",
                    f"**Missing Requirements:**\n" + "\n".join(f"• {error}" for error in validation_errors) + f"\n\n{progress_summary}"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            # Create the rank request embed with enhanced info
            progress_summary = await rank_validator.get_rank_progress_summary(
                interaction.user.id, interaction.guild.id, role_id, member_role_ids, current_points
            )
            
            embed = create_success_embed(
                "📋 Rank Request Submitted",
                f"**{interaction.user.display_name}** has requested a rank promotion",
                "All requirements have been verified and the request is ready for admin review."
            )
            
            embed.add_field(
                name="━━━━━━━━━ Request Details ━━━━━━━━━",
                value=(
                    f"**▸ Requested by:** {interaction.user.display_name}\n"
                    f"**▸ Username:** {username}\n"
                    f"**▸ Requested Rank:** {target_role.name}"
                ),
                inline=False
            )
            
            embed.add_field(
                name="━━━━━━━━━ Qualification Status ━━━━━━━━━",
                value="✅ **All Requirements Met** - Ready for admin approval",
                inline=False
            )
            
            embed.add_field(
                name="━━━━━━━━━ Detailed Progress ━━━━━━━━━",
                value=progress_summary,
                inline=False
            )
            
            # Add the required image
            embed.set_image(url=image.url)
            embed.add_field(name="🖼️ Image", value="Attached", inline=False)
            
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text="Use the buttons below to approve or reject this request")

            # Create the approval view
            view = RankRequestView(interaction.user.id, role_id, username, self.bot)

            # Get Supreme Demon role for ping
            supreme_demon_role_id = 1304283446016868424  # From SPECIAL_ROLES in utils.py
            supreme_demon_role = interaction.guild.get_role(supreme_demon_role_id)
            ping_text = supreme_demon_role.mention if supreme_demon_role else "@Supreme Demon"

            # Send the request to the rank request channel
            await rank_request_channel.send(
                content=f"{ping_text} - New rank request needs review:",
                embed=embed,
                view=view
            )

            # Confirm to the user that their request was submitted
            confirmation_embed = create_success_embed(
                "Rank Request Submitted",
                f"Your request for **{target_role.name}** has been submitted for approval.\n"
                f"The Supreme Demon will review your request shortly."
            )
            
            await interaction.response.send_message(embed=confirmation_embed, ephemeral=True)
            
            logger.info(f"✅ Rank request submitted: {interaction.user.id} requested {target_role.name}")

        except Exception as e:
            logger.error(f"❌ Error in getrank command: {e}")
            embed = create_error_embed("Request Failed", f"An error occurred while submitting your rank request: {str(e)}")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ========================================
    # MASS COMMUNICATION COMMANDS
    # ========================================

    @app_commands.command(name="heavenlyorder", description="Send a message to all members with specified roles (Admin only)")
    @app_commands.describe(
        roles="Mention the roles (separate multiple roles with spaces: @role1 @role2)",
        message="The message to send to all members with these roles"
    )
    @app_commands.default_permissions(administrator=True)
    async def heavenly_order(self, interaction: discord.Interaction, roles: str, message: str):
        """Send DM to all members who have any of the specified roles"""
        try:
            await interaction.response.defer(ephemeral=True)
            
            # Parse role mentions from the roles parameter
            role_mentions = []
            words = roles.split()
            
            for word in words:
                # Extract role ID from mention format <@&123456789>
                if word.startswith('<@&') and word.endswith('>'):
                    try:
                        role_id = int(word[3:-1])
                        role = interaction.guild.get_role(role_id)
                        if role:
                            role_mentions.append(role)
                        else:
                            logger.warning(f"Role with ID {role_id} not found in guild")
                    except ValueError:
                        logger.warning(f"Invalid role mention format: {word}")
                # Also handle role names directly
                else:
                    role = discord.utils.get(interaction.guild.roles, name=word)
                    if role:
                        role_mentions.append(role)
            
            if not role_mentions:
                embed = create_error_embed(
                    "No Valid Roles",
                    "No valid roles were found. Please mention roles using @role format or provide exact role names."
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Collect all members who have any of the specified roles
            target_members = set()
            for role in role_mentions:
                target_members.update(role.members)
            
            if not target_members:
                embed = create_info_embed(
                    "No Members Found",
                    f"No members found with the specified roles: {', '.join(role.name for role in role_mentions)}"
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Create the DM embed
            dm_embed = create_info_embed(
                "📜 Heavenly Order",
                "A message from the Heavenly Demon Sect leadership",
                message
            )
            dm_embed.set_footer(text=f"Sent by {interaction.user.display_name}")
            
            # Send DMs and track results
            successful_sends = 0
            failed_sends = 0
            failed_members = []
            
            status_embed = create_info_embed(
                "Sending Messages...",
                f"Preparing to send messages to {len(target_members)} members...",
                "This may take a moment."
            )
            await interaction.followup.send(embed=status_embed)
            
            for member in target_members:
                try:
                    await member.send(embed=dm_embed)
                    successful_sends += 1
                    logger.info(f"✅ Sent Heavenly Order to {member.display_name} ({member.id})")
                except discord.Forbidden:
                    failed_sends += 1
                    failed_members.append(f"{member.display_name} (DMs closed)")
                    logger.warning(f"❌ Could not send DM to {member.display_name} - DMs closed")
                except discord.HTTPException as e:
                    failed_sends += 1
                    failed_members.append(f"{member.display_name} (HTTP error)")
                    logger.error(f"❌ HTTP error sending DM to {member.display_name}: {e}")
                except Exception as e:
                    failed_sends += 1
                    failed_members.append(f"{member.display_name} (unknown error)")
                    logger.error(f"❌ Error sending DM to {member.display_name}: {e}")
            
            # Create final result embed
            result_fields = []
            
            # Summary section
            result_fields.append({
                "name": "━━━━━━━━━ Delivery Summary ━━━━━━━━━",
                "value": (
                    f"**▸ Total Recipients:** {len(target_members)}\n"
                    f"**▸ Successfully Sent:** {successful_sends}\n"
                    f"**▸ Failed to Send:** {failed_sends}"
                ),
                "inline": False
            })
            
            # Target roles section
            result_fields.append({
                "name": "━━━━━━━━━ Target Roles ━━━━━━━━━",
                "value": "**▸ Roles:** " + ", ".join(f"`{role.name}`" for role in role_mentions),
                "inline": False
            })
            
            # Failed deliveries (if any)
            if failed_members:
                failed_list = failed_members[:10]  # Limit to first 10 failures
                if len(failed_members) > 10:
                    failed_list.append(f"... and {len(failed_members) - 10} more")
                
                result_fields.append({
                    "name": "━━━━━━━━━ Failed Deliveries ━━━━━━━━━",
                    "value": "**▸ Could not reach:**\n" + "\n".join(f"• {member}" for member in failed_list),
                    "inline": False
                })
            
            if successful_sends > 0:
                additional_info = "The order has been distributed across the sect.\n\n"
                for field in result_fields:
                    additional_info += f"**{field['name']}**\n{field['value']}\n\n"
                
                final_embed = create_success_embed(
                    "📜 Heavenly Order Delivered",
                    f"Your message has been sent to {successful_sends} members",
                    additional_info.strip()
                )
            else:
                additional_info = f"{result_fields[0]['value']}\nAll deliveries failed - check if members have DMs enabled."
                final_embed = create_error_embed(
                    "📜 Heavenly Order Failed",
                    "Could not deliver the message to any members",
                    additional_info
                )
            
            await interaction.followup.send(embed=final_embed)
            
            logger.info(f"📜 Heavenly Order sent by {interaction.user.display_name}: {successful_sends} successful, {failed_sends} failed")
            
        except Exception as e:
            logger.error(f"❌ Error in heavenly_order command: {e}")
            embed = create_error_embed("Command Failed", f"An error occurred while sending the Heavenly Order: {str(e)}")
            await interaction.followup.send(embed=embed)

    # ========================================
    # POINT TRANSFER COMMANDS
    # ========================================

    @app_commands.command(name="bulk_import_points", description="Bulk import points from another bot (Admin only)")
    @app_commands.describe(
        data_file="Upload a text file with format: username,points (one per line)",
        preview_only="Set to True to preview changes without applying them"
    )
    @app_commands.default_permissions(administrator=True)
    async def bulk_import_points(
        self, 
        interaction: discord.Interaction,
        data_file: discord.Attachment,
        preview_only: bool = False
    ):
        """Bulk import member points from another leaderboard bot"""
        try:
            await interaction.response.defer(ephemeral=False)
            
            # Validate file type
            if not data_file.filename.endswith(('.txt', '.csv')):
                embed = create_error_embed(
                    "Invalid File Type", 
                    "Please upload a .txt or .csv file containing the point data."
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Read file content
            file_content = await data_file.read()
            data = file_content.decode('utf-8').strip()
            
            # Parse the data
            lines = data.split('\n')
            import_data = []
            errors = []
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):  # Skip empty lines and comments
                    continue
                
                try:
                    # Parse username,points format
                    if ',' in line:
                        username, points_str = line.split(',', 1)
                        username = username.strip()
                        points = int(points_str.strip())
                        
                        # Validate points
                        if points < 0:
                            errors.append(f"Line {line_num}: Negative points not allowed ({username})")
                            continue
                        
                        import_data.append((username, points))
                    else:
                        errors.append(f"Line {line_num}: Invalid format '{line}' (should be: username,points)")
                        
                except ValueError:
                    errors.append(f"Line {line_num}: Invalid points value '{line}'")
                except Exception as e:
                    errors.append(f"Line {line_num}: Error parsing '{line}' - {str(e)}")
            
            if not import_data:
                embed = create_error_embed(
                    "No Valid Data Found",
                    "No valid username,points entries found in the file.",
                    f"Format should be: username,points (one per line)\nErrors: {len(errors)}"
                )
                await interaction.followup.send(embed=embed)
                return
            
            # Preview mode - show what would be imported
            if preview_only:
                preview_text = "```\n"
                for username, points in import_data[:15]:  # Show first 15 entries
                    preview_text += f"{username}: {points:,} points\n"
                
                if len(import_data) > 15:
                    preview_text += f"... and {len(import_data) - 15} more entries\n"
                preview_text += "```"
                
                embed = create_info_embed(
                    "Import Preview",
                    f"Found {len(import_data)} valid entries ready for import",
                    preview_text
                )
                
                if errors:
                    error_text = "\n".join(errors[:5])  # Show first 5 errors
                    if len(errors) > 5:
                        error_text += f"\n... and {len(errors) - 5} more errors"
                    embed.add_field(name="Parsing Errors", value=f"```\n{error_text}\n```", inline=False)
                
                embed.add_field(
                    name="Next Steps", 
                    value="Run the command again with `preview_only: False` to actually import the points.",
                    inline=False
                )
                
                await interaction.followup.send(embed=embed)
                return
            
            # Actually import the points
            successful_imports = 0
            failed_imports = []
            
            for username, points in import_data:
                try:
                    # Try to find the member by username
                    member = None
                    for guild_member in interaction.guild.members:
                        if (guild_member.display_name.lower() == username.lower() or 
                            guild_member.name.lower() == username.lower()):
                            member = guild_member
                            break
                    
                    if member:
                        # Set the user's points (this will add them to leaderboard if not exists)
                        success = await self.leaderboard_manager.database.set_user_points(
                            interaction.guild.id, 
                            member.id, 
                            points, 
                            member.display_name
                        )
                        
                        if success:
                            successful_imports += 1
                            logger.info(f"✅ Imported {points} points for {username}")
                        else:
                            failed_imports.append(f"{username}: Database error")
                    else:
                        failed_imports.append(f"{username}: Member not found in server")
                        
                except Exception as e:
                    failed_imports.append(f"{username}: {str(e)}")
                    logger.error(f"❌ Error importing points for {username}: {e}")
            
            # Create success report
            embed = create_success_embed(
                "Bulk Import Complete",
                f"Successfully imported points for {successful_imports} members",
                f"Total processed: {len(import_data)}"
            )
            
            if failed_imports:
                failure_text = "\n".join(failed_imports[:10])  # Show first 10 failures
                if len(failed_imports) > 10:
                    failure_text += f"\n... and {len(failed_imports) - 10} more failures"
                
                embed.add_field(
                    name="Import Failures", 
                    value=f"```\n{failure_text}\n```", 
                    inline=False
                )
            
            if errors:
                embed.add_field(
                    name="Parsing Errors", 
                    value=f"{len(errors)} lines had parsing errors", 
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
            logger.info(f"✅ Bulk import completed: {successful_imports} success, {len(failed_imports)} failed")
            
        except Exception as e:
            logger.error(f"❌ Error in bulk_import_points: {e}")
            embed = create_error_embed("Import Failed", f"An error occurred during bulk import: {str(e)}")
            await interaction.followup.send(embed=embed)

    # ========================================
    # BOUNTY COMMANDS
    # ========================================

    @app_commands.command(name="create_bounty", description="Create a new bounty for other members to complete")
    @app_commands.describe(
        title="Bounty title",
        description="Detailed description of what needs to be done",
        target_username="Username this bounty is about/for",
        reward_text="What you're offering as reward (custom text)",
        image1="First image (optional)",
        image2="Second image (optional)",
        image3="Third image (optional)",
        image4="Fourth image (optional)",
        image5="Fifth image (optional)"
    )
    async def create_bounty(
        self, 
        interaction: discord.Interaction,
        title: str,
        description: str,
        target_username: str,
        reward_text: str,
        image1: Optional[discord.Attachment] = None,
        image2: Optional[discord.Attachment] = None,
        image3: Optional[discord.Attachment] = None,
        image4: Optional[discord.Attachment] = None,
        image5: Optional[discord.Attachment] = None
    ):
        """Create a new bounty"""
        try:
            await interaction.response.defer(ephemeral=False)
            
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.followup.send(embed=embed)
                return
            
            # Collect image URLs
            images = []
            for img in [image1, image2, image3, image4, image5]:
                if img:
                    images.append(img.url)
            
            # Create the bounty
            bounty_id = await self.bounty_manager.create_bounty(
                guild_id=interaction.guild.id,
                creator_id=interaction.user.id,
                title=title,
                description=description,
                target_username=target_username,
                reward_text=reward_text,
                images=images
            )
            
            embed = create_success_embed(
                "Bounty Created Successfully!",
                f"**Bounty ID:** {bounty_id}\n"
                f"**Title:** {title}\n"
                f"**Target:** {target_username}\n"
                f"**Reward:** {reward_text}\n"
                f"**Images:** {len(images)} attached\n\n"
                f"Members can now use `/claim_bounty {bounty_id}` to claim this bounty!"
            )
            
            await interaction.followup.send(embed=embed, ephemeral=False)
            
            # Post bounty announcement to bounty channel if configured
            bounty_channel_id = await self.channel_config.get_bounty_channel(interaction.guild.id)
            if bounty_channel_id:
                bounty_channel = interaction.guild.get_channel(bounty_channel_id)
                if bounty_channel:
                    # Create bounty announcement embed
                    announcement_embed = create_info_embed(
                        "🎯 New Bounty Available!",
                        f"**{title}**\n\n"
                        f"**Creator:** {interaction.user.display_name}\n"
                        f"**Target:** {target_username}\n"
                        f"**Description:** {description}\n"
                        f"**Reward:** {reward_text} + 50 points\n"
                        f"**Images:** {len(images)} attached\n\n"
                        f"Use `/claim_bounty {bounty_id}` to claim this bounty!"
                    )
                    announcement_embed.add_field(
                        name="Bounty ID", 
                        value=f"`{bounty_id}`", 
                        inline=True
                    )
                    announcement_embed.set_footer(text="Complete bounties to earn points and rewards!")
                    
                    # Add first image if available
                    if images:
                        announcement_embed.set_image(url=images[0])
                    
                    try:
                        await bounty_channel.send(embed=announcement_embed)
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to send bounty announcement: {e}")
            
            logger.info(f"✅ User {interaction.user.id} created bounty {bounty_id}")
            
        except Exception as e:
            logger.error(f"❌ Error creating bounty: {e}")
            embed = create_error_embed("Failed to Create Bounty", str(e))
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="list_bounties", description="List all active bounties (open + claimed)")
    @app_commands.describe(status="Filter by bounty status (optional)")
    @app_commands.choices(status=[
        app_commands.Choice(name="All Active (Open + Claimed)", value="active"),
        app_commands.Choice(name="Open Only", value="open"),
        app_commands.Choice(name="Claimed Only", value="claimed"),
        app_commands.Choice(name="Submitted", value="submitted"),
        app_commands.Choice(name="Cancelled", value="cancelled")
    ])
    async def list_bounties(self, interaction: discord.Interaction, status: Optional[str] = "active"):
        """List bounties by status"""
        try:
            # Handle "active" status to show both open and claimed bounties
            if status == "active":
                open_bounties = await self.bounty_manager.list_bounties(interaction.guild.id, "open")
                claimed_bounties = await self.bounty_manager.list_bounties(interaction.guild.id, "claimed")
                bounties = open_bounties + claimed_bounties
                # Sort by created_at descending
                bounties.sort(key=lambda x: x['created_at'], reverse=True)
            else:
                bounties = await self.bounty_manager.list_bounties(interaction.guild.id, status)
            
            if not bounties:
                status_display = "active" if status == "active" else status
                embed = create_info_embed(
                    f"No {status_display.title()} Bounties",
                    f"There are currently no {status_display} bounties available.",
                    "Use `/create_bounty` to create one!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return
            
            # Create interactive bounty view
            view = InteractiveBountyView(bounties, self.bounty_manager, interaction.user.id, interaction.guild.id, status)
            
            # Create initial embed
            embed = await view.create_page_embed(interaction.guild)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error listing bounties: {e}")
            embed = create_error_embed("Failed to List Bounties", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="claim_bounty", description="Claim a bounty to work on")
    @app_commands.describe(bounty_id="ID of the bounty to claim")
    async def claim_bounty(self, interaction: discord.Interaction, bounty_id: str):
        """Claim a bounty"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get bounty details first
            bounty = await self.bounty_manager.get_bounty(bounty_id, interaction.guild.id)
            if not bounty:
                embed = create_error_embed("Bounty Not Found", f"No bounty found with ID: {bounty_id}")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Try to claim it
            success = await self.bounty_manager.claim_bounty(bounty_id, interaction.guild.id, interaction.user.id)
            
            if not success:
                embed = create_error_embed(
                    "Cannot Claim Bounty",
                    "This bounty may already be claimed, completed, or you might be the creator."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            embed = create_success_embed(
                "Bounty Claimed Successfully!",
                f"**Bounty:** {bounty['title']}\n"
                f"**Target:** {bounty['target_username']}\n"
                f"**Reward:** {bounty['reward_text']} + 50 points\n\n"
                f"Complete the task and use `/submit_bounty {bounty_id}` with your proof!"
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            logger.info(f"✅ User {interaction.user.id} claimed bounty {bounty_id}")
            
        except Exception as e:
            logger.error(f"❌ Error claiming bounty: {e}")
            embed = create_error_embed("Failed to Claim Bounty", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="submit_bounty", description="Submit proof of bounty completion")
    @app_commands.describe(
        bounty_id="ID of the bounty you completed",
        proof_text="Description of what you did/proof of completion",
        proof1="Proof image 1 (optional)",
        proof2="Proof image 2 (optional)",
        proof3="Proof image 3 (optional)",
        proof4="Proof image 4 (optional)",
        proof5="Proof image 5 (optional)"
    )
    async def submit_bounty(
        self,
        interaction: discord.Interaction,
        bounty_id: str,
        proof_text: str,
        proof1: Optional[discord.Attachment] = None,
        proof2: Optional[discord.Attachment] = None,
        proof3: Optional[discord.Attachment] = None,
        proof4: Optional[discord.Attachment] = None,
        proof5: Optional[discord.Attachment] = None
    ):
        """Submit bounty completion proof"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Collect proof images
            proof_images = []
            for img in [proof1, proof2, proof3, proof4, proof5]:
                if img:
                    proof_images.append(img.url)
            
            # Submit the bounty
            success = await self.bounty_manager.submit_bounty(
                bounty_id, interaction.guild.id, proof_text, proof_images
            )
            
            if not success:
                embed = create_error_embed(
                    "Cannot Submit Bounty",
                    "This bounty may not be claimed by you or doesn't exist."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get bounty details for notification
            bounty = await self.bounty_manager.get_bounty(bounty_id, interaction.guild.id)
            
            embed = create_success_embed(
                "Bounty Submitted for Approval!",
                f"**Bounty:** {bounty['title'] if bounty else 'Unknown'}\n"
                f"**Proof:** {proof_text}\n"
                f"**Images:** {len(proof_images)} attached\n\n"
                f"The bounty creator will review your submission."
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
            # Post to bounty approval channel and ping creator
            bounty_approval_channel_id = await self.channel_config.get_bounty_approval_channel(interaction.guild.id)
            if bounty_approval_channel_id:
                bounty_approval_channel = interaction.guild.get_channel(bounty_approval_channel_id)
                if bounty_approval_channel:
                    try:
                        approval_embed = create_info_embed(
                            "🎯 Bounty Submission for Review",
                            f"**Bounty ID:** `{bounty_id}`\n"
                            f"**Title:** {bounty['title'] if bounty else 'Unknown'}\n"
                            f"**Creator:** <@{bounty['creator_id'] if bounty else 'Unknown'}>\n"
                            f"**Submitted by:** {interaction.user.display_name}\n"
                            f"**Target:** {bounty['target_username'] if bounty else 'Unknown'}\n"
                            f"**Proof:** {proof_text}\n"
                            f"**Images:** {len(proof_images)} attached\n\n"
                            f"Creator can use `/approve_bounty {bounty_id}` to approve!"
                        )
                        
                        # Add proof images if available
                        if proof_images:
                            approval_embed.set_image(url=proof_images[0])
                        
                        # Send with creator ping  
                        creator_ping = f"<@{bounty['creator_id']}>" if bounty else "Creator"
                        await bounty_approval_channel.send(
                            f"{creator_ping} Your bounty has been submitted for approval!",
                            embed=approval_embed
                        )
                        
                        # Send additional images if more than 1 (limit to prevent API issues)
                        if len(proof_images) > 1:
                            additional_images = proof_images[1:4]  # Limit to 3 additional images max
                            for i, img_url in enumerate(additional_images, 2):
                                try:
                                    img_embed = create_info_embed(
                                        f"BOUNTY PROOF IMAGE {i}/{min(len(proof_images), 4)}",
                                        f"**Submitted by:** {interaction.user.display_name}",
                                        "Additional evidence for bounty completion verification"
                                    )
                                    img_embed.set_image(url=img_url)
                                    await bounty_approval_channel.send(embed=img_embed)
                                    await asyncio.sleep(0.5)  # Small delay to prevent rate limiting
                                except discord.HTTPException as e:
                                    logger.warning(f"⚠️ Failed to send additional bounty image {i}: {e}")
                                    break  # Stop sending more images if we hit API limits
                                
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to send bounty submission to bounty approval channel: {e}")
            
            # Notify creator via DM
            if bounty:
                creator = interaction.guild.get_member(bounty['creator_id'])
                if creator:
                    try:
                        creator_embed = create_info_embed(
                            "Bounty Submission Received",
                            f"**Bounty:** {bounty['title']}\n"
                            f"**Submitted by:** {interaction.user.display_name}\n"
                            f"**Proof:** {proof_text}\n\n"
                            f"Use `/approve_bounty {bounty_id}` to approve and award 50 points!"
                        )
                        await creator.send(embed=creator_embed)
                    except:
                        pass  # DM failed, that's okay
            
            logger.info(f"✅ User {interaction.user.id} submitted bounty {bounty_id}")
            
        except Exception as e:
            logger.error(f"❌ Error submitting bounty: {e}")
            embed = create_error_embed("Failed to Submit Bounty", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="approve_bounty", description="Approve a bounty completion (creators only)")
    @app_commands.describe(bounty_id="ID of the bounty to approve")
    async def approve_bounty(self, interaction: discord.Interaction, bounty_id: str):
        """Approve bounty completion"""
        try:
            await interaction.response.defer(ephemeral=False)
            
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.followup.send(embed=embed)
                return
            
            # Get bounty details
            bounty = await self.bounty_manager.get_bounty(bounty_id, interaction.guild.id)
            if not bounty:
                embed = create_error_embed("Bounty Not Found", f"No bounty found with ID: {bounty_id}")
                await interaction.followup.send(embed=embed)
                return
            
            # Check if user is the creator
            if bounty['creator_id'] != interaction.user.id:
                embed = create_error_embed("Permission Denied", "Only the bounty creator can approve submissions.")
                await interaction.followup.send(embed=embed)
                return
            
            # Get current completion count before approval
            current_completion_count = bounty.get('completion_count', 0)
            
            # Approve the bounty
            claimer_id = await self.bounty_manager.approve_bounty(bounty_id, interaction.guild.id)
            
            if not claimer_id:
                embed = create_error_embed("Cannot Approve", "This bounty may not be submitted or doesn't exist.")
                await interaction.followup.send(embed=embed)
                return
            
            # Get claimer info first
            claimer = interaction.guild.get_member(claimer_id)
            claimer_name = claimer.display_name if claimer else "Unknown"
            
            # Award 50 points to completer
            await self.leaderboard_manager.add_points(interaction.guild.id, claimer_id, 50, claimer_name)
            
            # Check if bounty will be deleted (2nd completion)
            if current_completion_count + 1 >= 2:
                embed = create_success_embed(
                    "Bounty Completed & Deleted!",
                    f"**Bounty:** {bounty['title']}\n"
                    f"**Completed by:** {claimer_name}\n"
                    f"**Points Awarded:** 50 points\n"
                    f"**Custom Reward:** {bounty['reward_text']}\n\n"
                    f"This bounty has been completed 2 times and has been automatically deleted!"
                )
            else:
                embed = create_success_embed(
                    "Bounty Approved!",
                    f"**Bounty:** {bounty['title']}\n"
                    f"**Completed by:** {claimer_name}\n"
                    f"**Points Awarded:** 50 points\n"
                    f"**Custom Reward:** {bounty['reward_text']}\n"
                    f"**Completion Count:** {current_completion_count + 1}/2\n\n"
                    f"The bounty is now available for claiming again!"
                )
            
            await interaction.followup.send(embed=embed)
            
            # Notify the completer
            if claimer:
                try:
                    completer_embed = create_success_embed(
                        "Bounty Approved - Points Awarded!",
                        f"**Bounty:** {bounty['title']}\n"
                        f"**Points Earned:** 50 points\n"
                        f"**Custom Reward:** {bounty['reward_text']}\n"
                        f"**Approved by:** {interaction.user.display_name}\n\n"
                        f"Congratulations on completing the bounty!"
                    )
                    await claimer.send(embed=completer_embed)
                except:
                    pass  # DM failed
            
            logger.info(f"✅ Bounty {bounty_id} approved by {interaction.user.id}, 50 points awarded to {claimer_id}")
            
        except Exception as e:
            logger.error(f"❌ Error approving bounty: {e}")
            embed = create_error_embed("Failed to Approve Bounty", str(e))
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="my_bounties", description="View your created and claimed bounties")
    async def my_bounties(self, interaction: discord.Interaction):
        """View user's bounties"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            bounties = await self.bounty_manager.get_user_bounties(interaction.guild.id, interaction.user.id)
            
            embed = discord.Embed(
                title="🎯 Your Bounties",
                description="Your created and claimed bounties",
                color=Colors.INFO
            )
            
            # Created bounties
            if bounties['created']:
                created_text = ""
                for bounty in bounties['created'][:5]:
                    status_emoji = {"open": "🟢", "claimed": "🟡", "submitted": "🟠", "completed": "✅", "cancelled": "❌"}
                    emoji = status_emoji.get(bounty['status'], "⚪")
                    completion_count = bounty.get('completion_count', 0)
                    created_text += f"{emoji} **{bounty['title']}** ({bounty['status']}) - {completion_count}/2 completions\n"
                    created_text += f"   Target: {bounty['target_username']} | Reward: {bounty['reward_text']}\n\n"
                
                embed.add_field(
                    name="📝 Created by You",
                    value=created_text or "No bounties created",
                    inline=False
                )
            
            # Claimed bounties
            if bounties['claimed']:
                claimed_text = ""
                for bounty in bounties['claimed'][:5]:
                    status_emoji = {"claimed": "🟡", "submitted": "🟠", "completed": "✅"}
                    emoji = status_emoji.get(bounty['status'], "⚪")
                    claimed_text += f"{emoji} **{bounty['title']}** ({bounty['status']})\n"
                    claimed_text += f"   Target: {bounty['target_username']} | Reward: {bounty['reward_text']} + 50pts\n\n"
                
                embed.add_field(
                    name="🎯 Claimed by You",
                    value=claimed_text or "No bounties claimed",
                    inline=False
                )
            
            if not bounties['created'] and not bounties['claimed']:
                embed.description = "You haven't created or claimed any bounties yet.\n\nUse `/create_bounty` to create one or `/list_bounties` to find bounties to claim!"
            
            embed.set_footer(text="🟢 Open | 🟡 Claimed | 🟠 Submitted | ✅ Completed | ❌ Cancelled")
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error getting user bounties: {e}")
            embed = create_error_embed("Failed to Get Bounties", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cancel_bounty", description="Cancel your bounty (creators only)")
    @app_commands.describe(bounty_id="ID of the bounty to cancel")
    async def cancel_bounty(self, interaction: discord.Interaction, bounty_id: str):
        """Cancel a bounty"""
        try:
            success = await self.bounty_manager.cancel_bounty(bounty_id, interaction.guild.id, interaction.user.id)
            
            if not success:
                embed = create_error_embed(
                    "Cannot Cancel Bounty",
                    "This bounty may not exist, not be created by you, or already be completed."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            embed = create_success_embed(
                "Bounty Cancelled",
                f"Bounty {bounty_id} has been cancelled and is no longer available."
            )
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            logger.info(f"✅ User {interaction.user.id} cancelled bounty {bounty_id}")
            
        except Exception as e:
            logger.error(f"❌ Error cancelling bounty: {e}")
            embed = create_error_embed("Failed to Cancel Bounty", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pendingapproval", description="View all quest submissions pending approval (Admin only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        questinfo="Show detailed information about a specific quest by Quest ID",
        completedinfo="Show detailed completion info with images for a specific Quest ID"
    )
    async def pending_approval(self, interaction: discord.Interaction, questinfo: str = None, completedinfo: str = None):
        """View all quest submissions pending approval, or get detailed info about a specific quest/submission"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Handle questinfo parameter - show detailed quest information
            if questinfo:
                quest = await self.quest_manager.get_quest(questinfo)
                if not quest:
                    embed = create_error_embed("Quest Not Found", f"No quest found with ID: {questinfo}")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Create detailed quest info embed
                embed = discord.Embed(
                    title="📋 Quest Information",
                    description=f"Detailed information for Quest ID: `{questinfo}`",
                    color=Colors.PRIMARY
                )
                
                # Get creator info
                creator = interaction.guild.get_member(quest.creator_id)
                creator_name = creator.display_name if creator else f"User ID: {quest.creator_id}"
                
                embed.add_field(
                    name="▬ QUEST DETAILS",
                    value=f"**Title:** {quest.title}\n**Description:** {quest.description}\n**Rank:** {quest.rank}\n**Reward:** {quest.reward}\n**Created by:** {creator_name}",
                    inline=False
                )
                
                # Format creation time
                created_time = quest.created_at.strftime('%d/%m/%Y %H:%M') if quest.created_at else "Unknown"
                embed.add_field(
                    name="▬ CREATION INFO",
                    value=f"**Created:** {created_time}\n**Quest ID:** `{quest.quest_id}`\n**Status:** {'Active' if quest.status == 'available' else 'Inactive'}",
                    inline=False
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return
            
            # Handle completedinfo parameter - show detailed completion with images
            if completedinfo:
                # Get pending approvals for this specific quest
                all_pending = await self.quest_manager.get_pending_approvals(interaction.guild.id)
                approval = None
                for pending in all_pending:
                    if pending['quest_id'] == completedinfo:
                        approval = pending
                        break
                
                if not approval:
                    embed = create_error_embed("Submission Not Found", f"No pending submission found for Quest ID: {completedinfo}")
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Create detailed completion embed matching your format
                embed = discord.Embed(
                    title="QUEST SUBMISSION | PENDING APPROVAL",
                    description=f"{approval['quest_title']} requires administrative review",
                    color=Colors.WARNING
                )
                
                # Quest details section
                embed.add_field(
                    name="▬ QUEST DETAILS",
                    value=f"Quest ID: {approval['quest_id']}\nTitle: {approval['quest_title']}\nRank: {approval['quest_rank']}",
                    inline=False
                )
                
                # Submitted by section
                user = interaction.guild.get_member(approval['user_id'])
                user_mention = user.mention if user else f"User ID: {approval['user_id']}"
                user_display = user.display_name if user else f"User ID: {approval['user_id']}"
                
                embed.add_field(
                    name="▬ SUBMITTED BY", 
                    value=f"User: {user_mention}\nDisplay Name: {user_display}\nUser ID: {approval['user_id']}",
                    inline=False
                )
                
                # Proof submitted section
                completed_time = approval['completed_at'].strftime('%d/%m/%Y %H:%M') if approval['completed_at'] else "Unknown"
                embed.add_field(
                    name="▬ PROOF SUBMITTED",
                    value=f"{approval['proof_text']}\n{completed_time}",
                    inline=False
                )
                
                # Send the embed
                await interaction.response.send_message(embed=embed, ephemeral=False)
                
                # Send images separately if they exist
                if approval.get('proof_image_urls') and len(approval['proof_image_urls']) > 0:
                    for i, image_url in enumerate(approval['proof_image_urls'][:5]):  # Limit to 5 images
                        try:
                            image_embed = discord.Embed(color=Colors.WARNING)
                            image_embed.set_image(url=image_url)
                            image_embed.set_footer(text=f"Image {i+1} of {len(approval['proof_image_urls'])}")
                            await interaction.followup.send(embed=image_embed)
                        except Exception as img_error:
                            logger.warning(f"Failed to send image {i+1}: {img_error}")
                
                return
            
            # Default behavior - show all pending approvals
            pending_approvals = await self.quest_manager.get_pending_approvals(interaction.guild.id)
            
            if not pending_approvals:
                embed = create_info_embed(
                    "No Pending Approvals",
                    "There are currently no quest submissions waiting for approval.",
                    "All submitted quests have been processed!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=False)
                return
            
            # Create embed
            embed = discord.Embed(
                title="📋 Pending Quest Approvals",
                description=f"Found {len(pending_approvals)} quest submissions awaiting approval",
                color=Colors.WARNING
            )
            
            # Add each pending approval as a field
            for i, approval in enumerate(pending_approvals[:10]):  # Limit to 10 to avoid embed limits
                # Get user info
                user = interaction.guild.get_member(approval['user_id'])
                user_name = user.display_name if user else f"User ID: {approval['user_id']}"
                
                # Get creator info
                creator = interaction.guild.get_member(approval['quest_creator_id'])
                creator_name = creator.display_name if creator else f"User ID: {approval['quest_creator_id']}"
                
                # Format submission time
                completed_time = approval['completed_at'].strftime('%Y-%m-%d %H:%M UTC') if approval['completed_at'] else "Unknown"
                
                # Create field value
                field_value = f"**Submitted by:** {user_name}\n"
                field_value += f"**Quest Creator:** {creator_name}\n"
                field_value += f"**Reward:** {approval['quest_reward']}\n"
                field_value += f"**Submitted:** {completed_time}\n"
                field_value += f"**Proof:** {approval['proof_text'][:100]}{'...' if len(approval['proof_text']) > 100 else ''}\n"
                field_value += f"**Images:** {len(approval['proof_image_urls'])} attached\n"
                field_value += f"**Quest ID:** `{approval['quest_id']}`"
                
                embed.add_field(
                    name=f"🎯 {approval['quest_title'][:50]}{'...' if len(approval['quest_title']) > 50 else ''}",
                    value=field_value,
                    inline=False
                )
            
            if len(pending_approvals) > 10:
                embed.set_footer(text=f"Showing first 10 of {len(pending_approvals)} pending approvals. Use /approve_quest <quest_id> <user_id> to approve.")
            else:
                embed.set_footer(text="Use /pendingapproval questinfo:<quest_id> or completedinfo:<quest_id> for detailed info.")
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error getting pending approvals: {e}")
            embed = create_error_embed("Failed to Get Pending Approvals", str(e))
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="deleteallquests", description="Delete ALL quests from the database (PERMANENT - Admin only)")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(confirm="Type 'DELETE ALL QUESTS' to confirm this permanent action")
    async def delete_all_quests(self, interaction: discord.Interaction, confirm: str):
        """Delete all quests from the database (PERMANENT ACTION)"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check confirmation text
            if confirm != "DELETE ALL QUESTS":
                embed = create_error_embed(
                    "Confirmation Required",
                    "To delete all quests, you must type exactly: `DELETE ALL QUESTS`",
                    "This action is permanent and cannot be undone!"
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer()
            
            # Perform the deletion
            deletion_stats = await self.db.delete_all_quests(interaction.guild.id)
            
            # Create success embed with deletion statistics
            embed = create_success_embed(
                "All Quests Deleted Successfully",
                "All quest data has been permanently removed from the database",
                "The slate has been wiped clean for a fresh start"
            )
            
            embed.add_field(
                name="━━━━━━━━━ DELETION SUMMARY ━━━━━━━━━",
                value=f"**Quests Deleted:** {deletion_stats['quests_deleted']}\n**Quest Progress Records:** {deletion_stats['quest_progress_deleted']}\n**Team Progress Records:** {deletion_stats['team_progress_deleted']}\n**Total Records Removed:** {sum(deletion_stats.values())}",
                inline=False
            )
            
            embed.add_field(
                name="━━━━━━━━━ NEXT STEPS ━━━━━━━━━",
                value="▸ All quest data has been cleared\n▸ User points and leaderboard remain intact\n▸ You can now create new quests with `/create_quest`\n▸ Previous quest history is permanently lost",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
            logger.info(f"✅ Admin {interaction.user.id} deleted all quests for guild {interaction.guild.id}")
            
        except Exception as e:
            logger.error(f"❌ Error deleting all quests: {e}")
            embed = create_error_embed("Failed to Delete Quests", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="synccommands", description="Manually sync slash commands (Admin only)")
    @app_commands.default_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        """Manually sync slash commands"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            
            # Clear and sync commands
            self.bot.tree.clear_commands(guild=None)
            
            # Global sync
            global_synced = await self.bot.tree.sync()
            
            # Guild-specific sync
            guild_synced = await self.bot.tree.sync(guild=interaction.guild)
            
            embed = create_success_embed(
                "Commands Synced Successfully",
                f"Slash commands have been refreshed and should now appear in Discord",
                f"**Global Commands:** {len(global_synced)}\n**Guild Commands:** {len(guild_synced)}\n\nCommands should appear within 1-5 minutes."
            )
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            logger.info(f"✅ Manual sync completed by {interaction.user.display_name}")
            
        except Exception as e:
            logger.error(f"❌ Error in manual sync: {e}")
            embed = create_error_embed("Sync Failed", f"Failed to sync commands: {str(e)}")
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="testembed", description="Display comprehensive showcase of all 27+ embed designs used in the bot")
    async def testembed(self, interaction: discord.Interaction):
        """Display all embed designs for testing and demonstration"""
        try:
            await interaction.response.defer()
            
            # Sample data for testing embeds
            sample_user = interaction.user
            sample_guild_name = interaction.guild.name if interaction.guild else "Test Guild"
            
            # 1. Success Embed
            success_embed = create_success_embed(
                "Quest Completed Successfully",
                "Your submission has been approved by the sect elders",
                "Contribution points have been awarded to your cultivation path",
                [{"name": "Reward", "value": "50 Contribution Points + Special Badge"}]
            )
            
            # 2. Error Embed
            error_embed = create_error_embed(
                "Insufficient Cultivation Level",
                "Your current rank does not meet the requirements for this quest",
                "You need to reach Inner Disciple rank before attempting this mission",
                [{"name": "Required Rank", "value": "Inner Disciple (500+ points)"}]
            )
            
            # 3. Info Embed
            info_embed = create_info_embed(
                "Sect Archives Updated",
                "New cultivation techniques have been added to the knowledge vault",
                "These techniques are available to all disciples of Core rank and above",
                [{"name": "New Techniques", "value": "Shadow Step, Demonic Aura, Blood Meridian"}]
            )
            
            # 4. Quest Embed (simulate quest data)
            from bot.models import QuestRank, QuestCategory, QuestStatus
            from datetime import datetime
            
            class MockQuest:
                def __init__(self):
                    self.quest_id = "TEST001"
                    self.title = "Collect Ancient Artifacts"
                    self.description = "Venture into the forbidden ruins to collect 3 ancient demon artifacts for the sect treasury"
                    self.rank = QuestRank.MEDIUM
                    self.category = QuestCategory.COLLECTING
                    self.status = QuestStatus.AVAILABLE
                    self.requirements = "Must have completed at least 5 previous quests and possess Inner Disciple rank or higher"
                    self.reward = "75 Contribution Points + Rare Cultivation Manual + Access to Advanced Training Grounds"
                    self.created_at = datetime.now()
            
            quest_embed = create_quest_embed(MockQuest())
            
            # 5. User Stats Embed
            sample_stats = {
                'points': 850,
                'quests_completed': 12,
                'quests_accepted': 15,
                'last_updated': datetime.now().isoformat()
            }
            
            user_stats_embed = create_user_stats_embed(
                sample_user,
                sample_stats,
                sample_guild_name
            )
            
            # 6. Promotion Embed
            promotion_embed = create_promotion_embed(
                sample_user,
                "Inner Disciple",
                "Core Disciple",
                850
            )
            
            # 7. Leaderboard Embed (sample data)
            sample_leaderboard = [
                {'rank': 1, 'username': 'DemonLord_Supreme', 'points': 2500, 'user_id': '123456789'},
                {'rank': 2, 'username': 'ShadowCultivator', 'points': 1800, 'user_id': '987654321'},
                {'rank': 3, 'username': 'BloodMaster', 'points': 1200, 'user_id': '456789123'}
            ]
            
            leaderboard_embed = create_leaderboard_embed(
                sample_leaderboard,
                1,  # current_page
                3,  # total_pages
                sample_guild_name,
                interaction.guild,
                5500  # total_guild_points
            )
            
            # 8. Team Quest Embed
            class MockTeamQuest:
                def __init__(self):
                    self.quest_id = "TQ_001"
                    self.title = "Raid the Ancient Temple"
                    self.description = "Unite your sect members to storm the forbidden temple and claim the hidden demon artifacts"
                    self.rank = QuestRank.HARD
                    self.status = QuestStatus.AVAILABLE
                    self.requirements = "Minimum 5 team members, Inner Disciple rank or higher"
                    self.reward = "200 Contribution Points per member + Legendary Demon Weapon + Team Cultivation Boost"
                    self.created_at = datetime.now()
            
            sample_team_members = [
                {'username': 'TeamLeader_Xian', 'user_id': '111111111'},
                {'username': 'SwordMaster_Yu', 'user_id': '222222222'},
                {'username': 'MysticHealer_Lin', 'user_id': '333333333'},
                {'username': 'BladeDancer_Wei', 'user_id': '444444444'},
                {'username': 'DragonFist_Chen', 'user_id': '555555555'}
            ]
            
            team_quest_embed = create_team_quest_embed(MockTeamQuest(), sample_team_members, show_members=True)
            
            # 9. Quest List Embed
            sample_quest_list = [
                MockQuest(),  # Reuse the quest from earlier
                type('Quest', (), {
                    'quest_id': 'Q_456',
                    'title': 'Defeat Shadow Beasts',
                    'description': 'Hunt down 10 shadow beasts in the Darkwood Forest',
                    'rank': QuestRank.EASY,
                    'category': QuestCategory.HUNTING,
                    'status': QuestStatus.AVAILABLE,
                    'reward': '25 Contribution Points',
                    'created_at': datetime.now()
                })()
            ]
            
            quest_list_embed = create_quest_list_embed(
                sample_quest_list,
                sample_guild_name,
                current_filter="All Difficulties",
                page=1,
                total_pages=1
            )
            
            # 10. Progress Bar Demo Embed (Visual progress indicators)
            progress_demo_embed = create_info_embed(
                "Progress Bar Demonstrations",
                "Visual progress indicators used throughout the bot",
                "These bars show completion status for various activities"
            )
            
            # Add progress bar examples
            progress_examples = [
                f"Quest Progress: {create_progress_bar(7, 10)}",
                f"Cultivation: {create_progress_bar(3, 5)}", 
                f"Team Formation: {create_progress_bar(8, 10)}",
                f"Monthly Goals: {create_progress_bar(15, 20)}"
            ]
            
            progress_demo_embed.add_field(
                name="━━━━━━━━━ Progress Indicators ━━━━━━━━━",
                value="\n".join(progress_examples),
                inline=False
            )
            
            # 11. Role Points Assignment Results Embed (Admin function)
            role_assignment_embed = create_success_embed(
                "Role Points Assignment Complete",
                "Successfully processed point assignment for role **@Core Disciple**",
                None,
                [
                    {"name": "Assignment Details", "value": "**Role:** Core Disciple\n**Points per member:** +100\n**Total points distributed:** +2,500", "inline": False},
                    {"name": "Results Summary", "value": "**Successful:** 25\n**Failed:** 0", "inline": True},
                    {"name": "Action Type", "value": "Points reward", "inline": True}
                ]
            )
            
            # 12. Role Information Embed (Admin inspection)
            role_info_embed = create_info_embed(
                "Role Information: Core Disciple",
                "Detailed information about the Core Disciple role",
                None,
                [
                    {"name": "Basic Information", "value": "**Name:** Core Disciple\n**ID:** 1268528848740290580\n**Mention:** Core Disciple\n**Position:** 15", "inline": False},
                    {"name": "Member Statistics", "value": "**Non-bot members:** 47\n**Bot members:** 0\n**Total members:** 47", "inline": True},
                    {"name": "Properties", "value": "**Displayed separately:** Yes\n**Mentionable:** Yes", "inline": True}
                ]
            )
            
            # 13. Guild Roles List Embed (Server overview)
            roles_list_embed = create_info_embed(
                f"Roles in {sample_guild_name}",
                "Complete overview of server roles and member distribution",
                "Total roles: 23",
                [
                    {"name": "Senior Roles", "value": "**Demon God:** 1 member\n**Heavenly Demon:** 2 members\n**Supreme Demon:** 3 members\n**Guardian:** 5 members\n**Core Disciple:** 47 members", "inline": True},
                    {"name": "Standard Roles", "value": "**Inner Disciple:** 89 members\n**Outer Disciple:** 156 members\n**Quest Master:** 12 members\n**Leaderboard Pro:** 34 members", "inline": True}
                ]
            )
            
            # 14. Rank Request Approval Embed (User promotion)
            rank_approval_embed = create_success_embed(
                "RANK REQUEST APPROVED",
                "**ShadowCultivator** has been promoted to **Core Disciple**",
                "Congratulations on your advancement in the sect hierarchy",
                [
                    {"name": "Promotion Details", "value": "**Previous Rank:** Inner Disciple\n**New Rank:** Core Disciple\n**Points Required:** 750\n**Current Points:** 892", "inline": False},
                    {"name": "Approved By", "value": "Administrator", "inline": True}
                ]
            )
            
            # 15. Rank Request Rejection Embed (Promotion denied)
            rank_rejection_embed = create_error_embed(
                "RANK REQUEST REJECTED",
                "**BloodMaster**'s rank request has been rejected",
                "You need more contribution points to qualify for this rank",
                [
                    {"name": "Rejection Reason", "value": "**Insufficient contribution points**\n**Required:** 1000 points\n**Current:** 623 points", "inline": False},
                    {"name": "Next Steps", "value": "Complete more quests to earn points\nReapply when requirements are met", "inline": False}
                ]
            )
            
            # 16. Channel Configuration Embed (Setup completion)
            channel_config_embed = create_success_embed(
                "Channel Configuration Complete",
                "Quest channels have been successfully configured for this server",
                "Your bot is now ready to manage quests and leaderboards",
                [
                    {"name": "Configured Channels", "value": "**Quest Announcements:** Configured\n**Quest Submissions:** Configured\n**Admin Approvals:** Configured\n**Team Coordination:** Configured", "inline": False}
                ]
            )
            
            # 17. New Quest Available Embed (Quest announcements)
            new_quest_embed = discord.Embed(
                title="NEW QUEST AVAILABLE",
                description="**Hunt the Shadow Beasts**",
                color=get_quest_rank_color(QuestRank.MEDIUM)
            )
            new_quest_embed.add_field(
                name="━━━━━━━━━ Quest Details ━━━━━━━━━",
                value="**Difficulty:** Medium\n**Category:** Hunting\n**Reward:** 50 Contribution Points",
                inline=True
            )
            new_quest_embed.add_field(
                name="━━━━━━━━━ Requirements ━━━━━━━━━",
                value="**Minimum:** Inner Disciple rank\n**Recommended:** Team of 3-5 members",
                inline=True
            )
            new_quest_embed.set_footer(text="Quest Board • Fresh Mission Posted")
            
            # 18. Quest Board Pagination Embed (Quest listings)
            quest_board_embed = create_info_embed(
                f"Quest Board - {sample_guild_name}",
                "Browse available quests using navigation buttons",
                "**15** quests found",
                [
                    {"name": "Available Quests (Page 1/3)", "value": "**Collect Ancient Artifacts** (Medium)\n**Defeat Shadow Beasts** (Easy)\n**Gather Mystic Herbs** (Normal)\n**Temple Raid Mission** (Hard)\n**Meditation Challenge** (Easy)", "inline": False}
                ]
            )
            
            # 19. Personal Quest Dossier Embed (Individual history)
            quest_dossier_embed = create_info_embed(
                f"PERSONAL QUEST DOSSIER - {sample_user.display_name.upper()}",
                "Comprehensive overview of your quest achievements and performance",
                "Your complete sect quest history and accomplishments",
                [
                    {"name": "Quest Statistics", "value": "**Total Accepted:** 23\n**Completed:** 20\n**Approved:** 18\n**Rejected:** 2\n**Pending:** 3", "inline": True},
                    {"name": "Performance Metrics", "value": "**Success Rate:** 90%\n**Avg. Completion:** 2.3 days\n**Points Earned:** 1,450", "inline": True}
                ]
            )
            
            # 20. Quest Submission Approval Embed (Admin review)
            quest_approval_embed = create_info_embed(
                "QUEST SUBMISSION | PENDING APPROVAL",
                "**Collect Ancient Artifacts** requires administrative review",
                "Review the submission proof and take appropriate action",
                [
                    {"name": "Submission Details", "value": f"**Submitted by:** {sample_user.display_name}\n**Quest ID:** Q_789\n**Proof Images:** 3 attached", "inline": False},
                    {"name": "Admin Actions Required", "value": "Review submission proof\nVerify quest completion\nApprove or reject with feedback", "inline": False}
                ]
            )
            quest_approval_embed.set_image(url="https://via.placeholder.com/400x200/7289da/ffffff?text=Quest+Proof+Image")
            
            # 21. Additional Quest Images Embed (Multiple images)
            additional_image_embed = create_info_embed(
                "ADDITIONAL PROOF IMAGE 2/3",
                f"**Quest:** Collect Ancient Artifacts\n**Submitted by:** {sample_user.display_name}",
                "Additional evidence for quest completion verification"
            )
            additional_image_embed.set_image(url="https://via.placeholder.com/400x200/43b581/ffffff?text=Additional+Quest+Proof")
            
            # 22. Team Status Embed (Team information)
            team_status_embed = create_success_embed(
                "Team Status",
                "**Quest:** Raid the Ancient Temple\n**ID:** `TQ_001`",
                "Team is ready for collaborative quest completion",
                [
                    {"name": "Team Members (5/5)", "value": "**Leader:** TeamLeader_Xian\nSwordMaster_Yu\nMysticHealer_Lin\nBladeDancer_Wei\nDragonFist_Chen", "inline": False},
                    {"name": "Team Status", "value": "**Team:** Complete\n**Quest:** In Progress\n**Started:** 2 days ago", "inline": True}
                ]
            )
            
            # 23. User Teams Overview Embed (Personal teams)
            user_teams_embed = create_info_embed(
                "My Teams",
                f"Team overview for {sample_user.display_name}",
                "Your current and completed team quest participation",
                [
                    {"name": "Active Teams (2)", "value": "**Temple Explorers** (Leader)\n**Shadow Hunters** (Member)", "inline": False},
                    {"name": "Completed Teams (5)", "value": "Artifact Collectors\nBeast Slayers\nHerb Gatherers\nRuins Raiders\nCrystal Miners", "inline": False}
                ]
            )
            
            # 24. Available Teams Embed (Joinable teams)
            available_teams_embed = create_success_embed(
                "Teams Looking for Members",
                "Available teams you can join for collaborative quests",
                "Join a team to participate in group missions and earn shared rewards",
                [
                    {"name": "Open Teams (3/10 slots)", "value": "**Demon Slayers** (2/5 members)\n**Herb Collectors** (3/4 members)\n**Fortress Raiders** (1/6 members)", "inline": False},
                    {"name": "Join Instructions", "value": "Use `/join_team quest_id` to join a team\nContacting team leaders is recommended", "inline": False}
                ]
            )
            
            # 25. Rank Request Form Embed (Promotion request)
            rank_request_embed = create_info_embed(
                "RANK REQUEST FORM",
                f"**{sample_user.display_name}** has requested a rank promotion",
                "Request is pending administrative review and approval",
                [
                    {"name": "Current Status", "value": "**Current Rank:** Inner Disciple\n**Requested Rank:** Core Disciple\n**Current Points:** 892\n**Required Points:** 750", "inline": False},
                    {"name": "Eligibility", "value": "**Points Requirement:** Met\n**Quest Activity:** Sufficient\n**Sect Standing:** Good", "inline": True},
                    {"name": "Admin Review", "value": "**Status:** Awaiting decision\n**Estimated time:** 24 hours", "inline": True}
                ]
            )
            
            # 26. Bounties List Embed (Bounty listings)
            bounties_list_embed = create_info_embed(
                "AVAILABLE BOUNTIES",
                "Browse and claim bounties posted by other sect members",
                "Found 8 available bounties",
                [
                    {"name": "High Value Bounties", "value": "**Shadow Lord Elimination** - 500 points\n**Ancient Relic Recovery** - 300 points\n**Demon Beast Hunt** - 250 points", "inline": False},
                    {"name": "Standard Bounties", "value": "**Herb Collection Mission** - 100 points\n**Crystal Mining Task** - 75 points\n**Scout Patrol Duty** - 50 points", "inline": False}
                ]
            )
            
            # 27. User Bounties Embed (Personal bounty overview)
            user_bounties_embed = create_info_embed(
                "YOUR BOUNTIES",
                "Your created and claimed bounties overview",
                "Track your bounty activity and earnings",
                [
                    {"name": "Created Bounties (3)", "value": "**Beast Hunt Mission** - Available\n**Relic Recovery** - Claimed\n**Patrol Duty** - Completed", "inline": False},
                    {"name": "Claimed Bounties (2)", "value": "**Shadow Elimination** - In Progress\n**Crystal Mining** - Submitted", "inline": False},
                    {"name": "Bounty Statistics", "value": "**Total Created:** 15\n**Total Claimed:** 8\n**Success Rate:** 87%\n**Points Earned:** 2,350", "inline": False}
                ]
            )
            
            # Create a simplified showcase with key embed types (Discord follow-up limit workaround)
            key_embeds = [
                ("**CORE SYSTEM EMBEDS**", [success_embed, error_embed, info_embed]),
                ("**QUEST SYSTEM EMBEDS**", [quest_embed, user_stats_embed, quest_list_embed]),
                ("**ADMIN EMBEDS**", [role_assignment_embed, rank_approval_embed, channel_config_embed]),
                ("**PRESERVED DESIGNS**", [leaderboard_embed, new_quest_embed, quest_board_embed])
            ]
            
            # Send showcase summary first
            summary_embed = create_info_embed(
                "Complete Embed Showcase - 27+ Design Types",
                "Comprehensive visual design system for the Heavenly Demon Sect bot",
                "Updated with standardized styling while preserving 3 specified designs",
                [
                    {"name": "Updated Embeds (24+)", "value": "All embeds now use create_success_embed, create_error_embed, create_info_embed functions with consistent styling", "inline": False},
                    {"name": "Preserved Embeds (3)", "value": "LEADERBOARD, NEW QUEST AVAILABLE, QUEST LIST designs kept unchanged as requested", "inline": False},
                    {"name": "Design Features", "value": "Dynamic colors, ▸ bullet points, ━━━━━━━━━ separators, cultivation themes, proper Discord formatting", "inline": False},
                    {"name": "Categories Updated", "value": "Core System (10), Admin Management (3), Quest Workflow (8), User Management (4), Bounty System (2)", "inline": False}
                ]
            )
            
            await interaction.followup.send(
                content="**🎨 EMBED DESIGN SYSTEM SHOWCASE**",
                embed=summary_embed
            )
            
            # Send key embed examples in batches (max 10 total messages)
            message_count = 1  # Already sent summary
            for category_name, embeds_batch in key_embeds:
                if message_count >= 10:  # Respect Discord's follow-up limit
                    break
                    
                await asyncio.sleep(1)
                await interaction.followup.send(
                    content=category_name,
                    embeds=embeds_batch[:3]  # Max 3 embeds per message
                )
                message_count += 1
            
            logger.info(f"✅ User {interaction.user.id} viewed embed showcase (limited to {message_count} messages)")
            
            logger.info(f"✅ User {interaction.user.id} viewed all embed designs via testembed command")
            
        except Exception as e:
            logger.error(f"❌ Error in testembed command: {e}")
            embed = create_error_embed("Testembed Failed", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================== MENTOR MANAGEMENT COMMANDS ====================
    
    @app_commands.command(name="add_mentor", description="Add a new mentor to the welcome automation system (Admin only)")
    @app_commands.describe(
        user="The user to add as a mentor",
        game_specialization="Game specialization (any custom text, e.g., 'Murim Cultivation', 'Soul Cultivation', etc.)"
    )
    async def add_mentor(self, interaction: discord.Interaction, user: discord.Member, 
                        game_specialization: str = "general"):
        """Add a new mentor to the system"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                embed = create_error_embed("Permission Denied", "Only administrators can manage mentors.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user is a bot
            if user.bot:
                embed = create_error_embed("Invalid User", "Bots cannot be mentors.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Basic input validation (no restricted validation - allow any text)
            game_specialization = game_specialization.strip()
            if len(game_specialization) > 100:
                embed = create_error_embed(
                    "Invalid Game Specialization", 
                    "Game specialization must be 100 characters or less."
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            if not game_specialization:
                game_specialization = "general"
            
            # Add mentor using welcome manager with game specialization
            success = await self.bot.welcome_manager.add_mentor(user.id, interaction.guild.id, game_specialization)
            
            if success:
                # Auto-create mentor channel when mentor is added
                channel = await self.bot.mentor_channel_manager.create_mentor_channel(user, interaction.guild)
                
                if channel:
                    embed = create_success_embed(
                        "Mentor Added Successfully",
                        f"**{user.display_name}** has been added as a mentor",
                        f"**Specialization:** {game_specialization}\n**Dedicated Channel:** {channel.mention}\n\nThey will now be available to guide new disciples in their chosen cultivation path.",
                        [{"name": "Mentor Details", "value": f"**User:** {user.mention}\n**User ID:** {user.id}\n**Game Specialization:** {game_specialization.title()}\n**Channel:** {channel.mention}\n**Status:** Active"}]
                    )
                    logger.info(f"✅ Admin {interaction.user.display_name} added mentor {user.display_name} with channel {channel.name} in guild {interaction.guild.id}")
                else:
                    embed = create_success_embed(
                        "Mentor Added Successfully",
                        f"**{user.display_name}** has been added as a mentor",
                        f"**Specialization:** {game_specialization}\n**Warning:** Channel creation failed, but mentor was added successfully.",
                        [{"name": "Mentor Details", "value": f"**User:** {user.mention}\n**User ID:** {user.id}\n**Game Specialization:** {game_specialization.title()}\n**Status:** Active (no channel)"}]
                    )
                    logger.warning(f"⚠️ Mentor {user.display_name} added but channel creation failed in guild {interaction.guild.id}")
            else:
                embed = create_error_embed("Failed to Add Mentor", "An error occurred while adding the mentor to the database.")
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error in add_mentor command: {e}")
            embed = create_error_embed("Command Failed", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove_mentor", description="Remove a mentor from the welcome automation system (Admin only)")
    @app_commands.describe(user="The user to remove as a mentor")
    async def remove_mentor(self, interaction: discord.Interaction, user: discord.Member):
        """Remove a mentor from the system"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                embed = create_error_embed("Permission Denied", "Only administrators can manage mentors.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Remove mentor using welcome manager
            success = await self.bot.welcome_manager.remove_mentor(user.id, interaction.guild.id)
            
            if success:
                embed = create_success_embed(
                    "Mentor Removed Successfully",
                    f"**{user.display_name}** has been removed as a mentor",
                    "They will no longer be assigned new students.",
                    [{"name": "Removed Mentor", "value": f"**User:** {user.mention}\n**User ID:** {user.id}\n**Status:** Inactive"}]
                )
                logger.info(f"✅ Admin {interaction.user.display_name} removed mentor {user.display_name} in guild {interaction.guild.id}")
            else:
                embed = create_error_embed("Failed to Remove Mentor", "An error occurred while removing the mentor from the database.")
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            
        except Exception as e:
            logger.error(f"❌ Error in remove_mentor command: {e}")
            embed = create_error_embed("Command Failed", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="list_mentors", description="View all active mentors in the welcome automation system (Admin only)")
    async def list_mentors(self, interaction: discord.Interaction):
        """List all active mentors for this guild"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                embed = create_error_embed("Permission Denied", "Only administrators can view mentor lists.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Get mentor list from welcome manager
            mentors = await self.bot.welcome_manager.list_mentors(interaction.guild.id)
            
            if not mentors:
                embed = create_info_embed(
                    "No Active Mentors",
                    "There are currently no active mentors configured for this server.",
                    "Use `/add_mentor` to add mentors to the welcome automation system."
                )
            else:
                mentor_info = ""
                mentor_count = 0
                
                for mentor_data in mentors:
                    member = interaction.guild.get_member(mentor_data['user_id'])
                    if member:
                        mentor_count += 1
                        # Get current mentee count
                        try:
                            async with self.bot.database.pool.acquire() as conn:
                                mentee_count = await conn.fetchval('''
                                    SELECT COUNT(*) FROM welcome_automation 
                                    WHERE mentor_id = $1 AND guild_id = $2 AND new_disciple_role_awarded = FALSE
                                ''', mentor_data['user_id'], interaction.guild.id)
                        except:
                            mentee_count = 0
                            
                        mentor_info += f"**{mentor_count}. {member.display_name}**\n"
                        mentor_info += f"   ▸ User ID: {mentor_data['user_id']}\n"
                        mentor_info += f"   ▸ Game Specialization: {mentor_data.get('game_specialization', 'general').title()}\n"
                        mentor_info += f"   ▸ Current Students: {mentee_count or 0}\n"
                        mentor_info += f"   ▸ Added: {mentor_data['added_date'].strftime('%Y-%m-%d')}\n\n"
                
                embed = create_success_embed(
                    f"Active Mentors ({mentor_count})",
                    f"Welcome automation mentors for **{interaction.guild.name}**",
                    "These mentors will be automatically assigned to new members.",
                    [{"name": "━━━━━━━━━ Mentor List ━━━━━━━━━", "value": mentor_info.strip() if mentor_info else "No valid mentors found"}]
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=False)
            logger.info(f"✅ Admin {interaction.user.display_name} viewed mentor list in guild {interaction.guild.id}")
            
        except Exception as e:
            logger.error(f"❌ Error in list_mentors command: {e}")
            embed = create_error_embed("Command Failed", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mentor_stats", description="View detailed statistics for all mentors (Admin only)")
    @app_commands.describe(
        mentor="Optional: View detailed stats for a specific mentor (can mention or type name)"
    )
    async def mentor_stats(self, interaction: discord.Interaction, mentor: discord.Member = None):
        """Display comprehensive mentor statistics including detailed student information"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check admin permissions
            if not interaction.user.guild_permissions.administrator:
                embed = create_error_embed("Permission Denied", "Only administrators can view mentor statistics.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Defer response for processing time
            await interaction.response.defer()
            
            async with self.bot.database.pool.acquire() as conn:
                # Get mentor statistics with student details
                if mentor:
                    # Check if the mentioned user is actually a mentor
                    mentor_check = await conn.fetchrow('''
                        SELECT user_id FROM mentors 
                        WHERE user_id = $1 AND guild_id = $2 AND is_active = TRUE
                    ''', mentor.id, interaction.guild.id)
                    
                    if not mentor_check:
                        embed = create_error_embed("Not a Mentor", f"{mentor.display_name} is not an active mentor in the system.")
                        await interaction.followup.send(embed=embed, ephemeral=True)
                        return
                    
                    mentor_filter = "AND m.user_id = $2"
                    mentor_params = [interaction.guild.id, mentor.id]
                else:
                    mentor_filter = ""
                    mentor_params = [interaction.guild.id]
                
                # Get comprehensive mentor data
                mentor_query = f'''
                    SELECT 
                        m.user_id,
                        m.game_specialization,
                        m.current_students,
                        m.added_date,
                        COUNT(wa.user_id) as actual_students
                    FROM mentors m
                    LEFT JOIN welcome_automation wa ON m.user_id = wa.mentor_id AND m.guild_id = wa.guild_id
                    WHERE m.guild_id = $1 AND m.is_active = TRUE {mentor_filter}
                    GROUP BY m.user_id, m.game_specialization, m.current_students, m.added_date
                    ORDER BY actual_students DESC, m.added_date ASC
                '''
                
                mentor_stats = await conn.fetch(mentor_query, *mentor_params)
                
                if not mentor_stats:
                    embed = create_info_embed(
                        "No Active Mentors",
                        "There are currently no active mentors in the system.",
                        "Use `/add_mentor` to add mentors to the welcome automation system."
                    )
                    await interaction.followup.send(embed=embed)
                    return
                
                # Get detailed student information for each mentor
                detailed_mentors = []
                total_students = 0
                total_points_generated = 0
                
                for mentor_data in mentor_stats:
                    member = interaction.guild.get_member(mentor_data['user_id'])
                    if not member:
                        continue
                    
                    # Get mentor's students with detailed info
                    students_data = await conn.fetch('''
                        SELECT 
                            wa.user_id,
                            wa.join_date,
                            COALESCE((wa.quest_1_completed AND wa.quest_2_completed), false) as completed_starter_quests,
                            wa.last_activity,
                            COALESCE(lb.points, 0) as points,
                            lb.username,
                            COALESCE(us.quests_completed, 0) as quests_completed,
                            COALESCE(us.quests_accepted, 0) as quests_accepted,
                            COALESCE(wa.new_disciple_role_awarded, false) as new_disciple_role_awarded
                        FROM welcome_automation wa
                        LEFT JOIN leaderboard lb ON wa.user_id = lb.user_id AND wa.guild_id = lb.guild_id
                        LEFT JOIN user_stats us ON wa.user_id = us.user_id AND wa.guild_id = us.guild_id
                        WHERE wa.mentor_id = $1 AND wa.guild_id = $2
                        ORDER BY lb.points DESC NULLS LAST, wa.join_date DESC
                    ''', mentor_data['user_id'], interaction.guild.id)
                    
                    # Calculate mentor performance metrics
                    student_count = len(students_data)
                    completed_starter_count = sum(1 for s in students_data if s.get('completed_starter_quests', False))
                    success_rate = (completed_starter_count / student_count * 100) if student_count > 0 else 0
                    
                    # Calculate total points generated by students
                    mentor_points_generated = sum(s.get('points', 0) or 0 for s in students_data)
                    total_points_generated += mentor_points_generated
                    
                    # Get mentor's rank and points
                    mentor_stats_data = await self.bot.leaderboard_manager.get_user_stats(interaction.guild.id, member.id)
                    mentor_points = mentor_stats_data['points'] if mentor_stats_data else 0
                    mentor_rank = get_rank_title_by_points(mentor_points, member)
                    
                    # Calculate average student retention (days since joining)
                    from datetime import datetime, timezone
                    current_time = datetime.now(timezone.utc)
                    retention_days = []
                    for student in students_data:
                        if student['join_date']:
                            join_date = student['join_date']
                            # Ensure join_date is timezone-aware
                            if join_date.tzinfo is None:
                                join_date = join_date.replace(tzinfo=timezone.utc)
                            days_mentored = (current_time - join_date).days
                            retention_days.append(days_mentored)
                    
                    avg_retention = sum(retention_days) / len(retention_days) if retention_days else 0
                    
                    detailed_mentors.append({
                        'member': member,
                        'data': mentor_data,
                        'students': students_data,
                        'student_count': student_count,
                        'success_rate': success_rate,
                        'points_generated': mentor_points_generated,
                        'mentor_points': mentor_points,
                        'mentor_rank': mentor_rank,
                        'avg_retention': avg_retention,
                        'completed_starter_count': completed_starter_count
                    })
                    
                    total_students += student_count
                
                # Create enhanced embed
                if mentor and len(detailed_mentors) == 1:
                    # Detailed view for single mentor
                    await self._send_detailed_mentor_view(interaction, detailed_mentors[0])
                else:
                    # Overview for all mentors
                    await self._send_mentor_overview(interaction, detailed_mentors, total_students, total_points_generated)
                    
        except Exception as e:
            logger.error(f"❌ Error in enhanced mentor_stats command: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            embed = create_error_embed("Command Failed", f"An error occurred: {str(e)}")
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
    
    async def _send_detailed_mentor_view(self, interaction: discord.Interaction, mentor_info: dict):
        """Send detailed view for a single mentor"""
        member = mentor_info['member']
        students = mentor_info['students']
        
        embed = create_success_embed(
            f"Detailed Mentor Statistics - {member.display_name}",
            f"**Rank:** {mentor_info['mentor_rank']} • **Points:** {mentor_info['mentor_points']:,}",
            f"**Specialization:** {mentor_info['data']['game_specialization'].title()}"
        )
        
        # Mentor performance metrics
        performance_info = (
            f"**▸ Total Students:** {mentor_info['student_count']}\n"
            f"**▸ Success Rate:** {mentor_info['success_rate']:.1f}% ({mentor_info['completed_starter_count']}/{mentor_info['student_count']} completed starters)\n"
            f"**▸ Points Generated:** {mentor_info['points_generated']:,} pts\n"
            f"**▸ Average Retention:** {mentor_info['avg_retention']:.1f} days\n"
            f"**▸ Mentor Since:** {mentor_info['data']['added_date'].strftime('%Y-%m-%d')}"
        )
        
        embed.add_field(
            name="━━━━━━━━━ Performance Metrics ━━━━━━━━━",
            value=performance_info,
            inline=False
        )
        
        # Student details (limit to top 10 for embed space)
        if students:
            students_info = ""
            for i, student in enumerate(students[:10], 1):
                student_member = interaction.guild.get_member(student['user_id'])
                if student_member:
                    student_points = student['points'] or 0
                    student_rank = get_rank_title_by_points(student_points, student_member)
                    quests_completed = student['quests_completed'] or 0
                    
                    # Calculate days as student
                    from datetime import datetime, timezone
                    if student['join_date']:
                        join_date = student['join_date']
                        # Ensure join_date is timezone-aware
                        if join_date.tzinfo is None:
                            join_date = join_date.replace(tzinfo=timezone.utc)
                        days_mentored = (datetime.now(timezone.utc) - join_date).days
                    else:
                        days_mentored = 0
                    
                    starter_status = "✅" if student['completed_starter_quests'] else "❌"
                    
                    students_info += (
                        f"**{i}. {student_member.display_name}**\n"
                        f"   ▸ **Rank:** {student_rank} • **Points:** {student_points:,}\n"
                        f"   ▸ **Quests:** {quests_completed} • **Days:** {days_mentored}\n"
                        f"   ▸ **Starter Quests:** {starter_status}\n\n"
                    )
            
            if len(students) > 10:
                students_info += f"... and {len(students) - 10} more students"
            
            embed.add_field(
                name="━━━━━━━━━ Student Details ━━━━━━━━━",
                value=students_info.strip() if students_info else "No active students",
                inline=False
            )
        else:
            embed.add_field(
                name="━━━━━━━━━ Student Details ━━━━━━━━━",
                value="No students currently assigned to this mentor",
                inline=False
            )
        
        await interaction.followup.send(embed=embed)
    
    async def _send_mentor_overview(self, interaction: discord.Interaction, mentors: list, total_students: int, total_points: int):
        """Send overview for all mentors"""
        mentor_count = len(mentors)
        
        embed = create_success_embed(
            f"Mentor Statistics Overview ({mentor_count} Active)",
            f"Complete performance overview for **{interaction.guild.name}**",
            f"**Total Students:** {total_students} • **Total Points Generated:** {total_points:,}"
        )
        
        # Build mentor summary
        mentor_info = ""
        for i, mentor_data in enumerate(mentors[:15], 1):  # Limit to 15 for embed space
            member = mentor_data['member']
            
            mentor_info += (
                f"**{i}. {member.display_name}** ({mentor_data['mentor_rank']})\n"
                f"   ▸ **Specialization:** {mentor_data['data']['game_specialization'].title()}\n"
                f"   ▸ **Students:** {mentor_data['student_count']} • **Success:** {mentor_data['success_rate']:.1f}%\n"
                f"   ▸ **Points Generated:** {mentor_data['points_generated']:,} pts\n\n"
            )
        
        if len(mentors) > 15:
            mentor_info += f"... and {len(mentors) - 15} more mentors"
        
        embed.add_field(
            name="━━━━━━━━━ Mentor Performance ━━━━━━━━━",
            value=mentor_info.strip() if mentor_info else "No valid mentors found",
            inline=False
        )
        
        # Calculate overall statistics
        avg_students = total_students / mentor_count if mentor_count > 0 else 0
        avg_success_rate = sum(m['success_rate'] for m in mentors) / mentor_count if mentor_count > 0 else 0
        avg_points_generated = total_points / mentor_count if mentor_count > 0 else 0
        
        summary_info = (
            f"**▸ Active Mentors:** {mentor_count}\n"
            f"**▸ Total Students:** {total_students}\n"
            f"**▸ Average Students per Mentor:** {avg_students:.1f}\n"
            f"**▸ Average Success Rate:** {avg_success_rate:.1f}%\n"
            f"**▸ Average Points per Mentor:** {avg_points_generated:,.0f}"
        )
        
        embed.add_field(
            name="━━━━━━━━━ Overall Statistics ━━━━━━━━━",
            value=summary_info,
            inline=False
        )
        
        # Add usage tip
        embed.add_field(
            name="━━━━━━━━━ Usage Tip ━━━━━━━━━",
            value="Use `/mentor_stats mentor: @[user]` to view detailed statistics for a specific mentor",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="choose_mentor", description="Choose a new mentor or leave your current mentor")
    @app_commands.describe(
        action="Choose whether to select a new mentor or leave your current one"
    )
    async def choose_mentor(self, interaction: discord.Interaction, 
                           action: typing.Literal["select_mentor", "leave_mentor"]):
        """Allow students to choose or leave mentors"""
        try:
            # Safety check for guild
            if not interaction.guild:
                embed = create_error_embed("Server Error", "This command must be used in a server.")
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # Check if user has welcome automation record
            async with self.bot.database.pool.acquire() as conn:
                user_record = await conn.fetchrow('''
                    SELECT mentor_id, new_disciple_role_awarded FROM welcome_automation
                    WHERE user_id = $1 AND guild_id = $2
                ''', interaction.user.id, interaction.guild.id)
            
            if action == "leave_mentor":
                if not user_record or not user_record['mentor_id']:
                    embed = create_info_embed(
                        "No Mentor Assigned",
                        "You don't currently have a mentor to leave.",
                        "Use `/choose_mentor select_mentor` to get a mentor."
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Remove from current mentor
                current_mentor = interaction.guild.get_member(user_record['mentor_id'])
                
                async with self.bot.database.pool.acquire() as conn:
                    # Remove mentor assignment
                    await conn.execute('''
                        UPDATE welcome_automation 
                        SET mentor_id = NULL, last_activity = CURRENT_TIMESTAMP
                        WHERE user_id = $1 AND guild_id = $2
                    ''', interaction.user.id, interaction.guild.id)
                    
                    # Decrease mentor's student count
                    await conn.execute('''
                        UPDATE mentors 
                        SET current_students = GREATEST(current_students - 1, 0)
                        WHERE user_id = $1 AND guild_id = $2
                    ''', user_record['mentor_id'], interaction.guild.id)
                
                # Remove from mentor channel
                if current_mentor and self.bot.mentor_channel_manager:
                    await self.bot.mentor_channel_manager.remove_student_from_mentor_channel(
                        interaction.user, current_mentor
                    )
                
                embed = create_success_embed(
                    "Mentor Removed Successfully",
                    f"You have left **{current_mentor.display_name if current_mentor else 'your mentor'}**'s guidance",
                    "You can choose a new mentor anytime using `/choose_mentor select_mentor`."
                )
                
                await interaction.response.send_message(embed=embed, ephemeral=True)
                logger.info(f"✅ {interaction.user.display_name} left their mentor in guild {interaction.guild.id}")
                
            elif action == "select_mentor":
                if user_record and user_record['mentor_id']:
                    current_mentor = interaction.guild.get_member(user_record['mentor_id'])
                    embed = create_info_embed(
                        "Already Have Mentor",
                        f"You are currently being guided by **{current_mentor.display_name if current_mentor else 'a mentor'}**",
                        "Use `/choose_mentor leave_mentor` first if you want to change mentors."
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                
                # Create or update welcome automation record if needed
                if not user_record:
                    async with self.bot.database.pool.acquire() as conn:
                        await conn.execute('''
                            INSERT INTO welcome_automation (user_id, guild_id, new_disciple_role_awarded, last_activity)
                            VALUES ($1, $2, FALSE, CURRENT_TIMESTAMP)
                            ON CONFLICT (user_id, guild_id) DO NOTHING
                        ''', interaction.user.id, interaction.guild.id)
                
                # Load dynamic games for this guild
                guild_games = await self.bot.welcome_manager.get_guild_games(interaction.guild.id)
                
                # Create mentor selection view
                from bot.welcome_manager import GameMentorSelectionView
                game_view = GameMentorSelectionView(interaction.user, self.bot.database, self.bot.welcome_manager, guild_games)
                
                embed = create_info_embed(
                    "Choose Your Cultivation Path",
                    f"Select your preferred specialization for mentorship, {interaction.user.display_name}"
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
                
                await interaction.response.send_message(embed=embed, view=game_view, ephemeral=True)
                
        except Exception as e:
            logger.error(f"❌ Error in choose_mentor command: {e}")
            embed = create_error_embed("Command Failed", str(e))
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="test_reincarnation", description="[ADMIN] Test the reincarnation system for a user")
    @app_commands.describe(user="User to test reincarnation for")
    async def test_reincarnation(self, interaction: discord.Interaction, user: discord.Member):
        """Test the reincarnation system by simulating a member's return"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            embed = create_error_embed("Permission Denied", "Only administrators can use this test command.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Import the reincarnation functions
            from bot.events import check_member_reincarnation, send_reincarnation_notification
            from bot.models import DepartedMember
            from datetime import datetime, timezone
            
            # Check if user already has a departed member record
            existing_record = await self.bot.database.get_departed_member(user.id, interaction.guild.id)
            
            if not existing_record:
                # Create a simple test record directly in database to avoid timezone issues
                logger.info(f"🧪 Creating test departed member record for {user.display_name}")
                
                async with self.bot.database.pool.acquire() as conn:
                    await conn.execute('''
                        INSERT INTO departed_members (member_id, guild_id, username, display_name, 
                                                    avatar_url, highest_role, total_points, leave_date, times_left, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, NOW())
                    ''', user.id, interaction.guild.id, user.name, user.display_name,
                        str(user.avatar.url) if user.avatar else None, "Test Role", 100, 1)
                
                embed = create_info_embed(
                    "Test Record Created", 
                    f"Created test departed member record for {user.display_name}",
                    "Now testing reincarnation notification..."
                )
                await interaction.followup.send(embed=embed)
            
            # Now test the reincarnation system
            await check_member_reincarnation(user, self.bot)
            
            embed = create_success_embed(
                "Reincarnation Test Complete",
                f"Successfully tested reincarnation system for {user.display_name}",
                "Check the reincarnation channel for the notification. If no notification appeared, check the logs for debugging information."
            )
            await interaction.followup.send(embed=embed)
            logger.info(f"🔄 Admin {interaction.user.display_name} tested reincarnation for {user.display_name}")
            
        except Exception as e:
            logger.error(f"❌ Error in test_reincarnation command: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            embed = create_error_embed("Test Failed", f"Error testing reincarnation: {str(e)}")
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="test_reincarnation_v2", description="[ADMIN] Alternative test for reincarnation notifications")
    @app_commands.describe(user="User to test reincarnation notification for")
    async def test_reincarnation_v2(self, interaction: discord.Interaction, user: discord.Member):
        """Test reincarnation notification directly without database creation"""
        # Check if user has admin permissions
        if not interaction.user.guild_permissions.administrator:
            embed = create_error_embed("Permission Denied", "Only administrators can use this test command.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        await interaction.response.defer()
        
        try:
            # Import the reincarnation functions
            from bot.events import send_reincarnation_notification
            from bot.models import DepartedMember
            from datetime import datetime, timezone
            
            # Create a mock departed member for testing notification
            mock_departed_member = DepartedMember(
                member_id=user.id,
                guild_id=interaction.guild.id,
                username=user.name,
                display_name=user.display_name,
                avatar_url=str(user.avatar.url) if user.avatar else None,
                highest_role="Test Role",
                total_points=100,
                join_date=datetime.now(timezone.utc),
                leave_date=datetime.now(timezone.utc),
                times_left=2,
                funeral_message="Test funeral message",
                created_at=datetime.now(timezone.utc)
            )
            
            # Test reincarnation notification directly
            logger.info(f"🧪 Testing reincarnation notification for {user.display_name}")
            await send_reincarnation_notification(user, mock_departed_member, self.bot)
            
            embed = create_success_embed(
                "Reincarnation Notification Test Complete",
                f"Sent test reincarnation notification for {user.display_name}",
                "Check the reincarnation channel or fallback channel for the notification."
            )
            await interaction.followup.send(embed=embed)
            logger.info(f"🔄 Admin {interaction.user.display_name} tested reincarnation notification for {user.display_name}")
            
        except Exception as e:
            logger.error(f"❌ Error in test_reincarnation_v2 command: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            embed = create_error_embed("Test Failed", f"Error testing reincarnation notification: {str(e)}")
            await interaction.followup.send(embed=embed)
            return
        
        await interaction.response.defer()
        
        try:
            # Import the reincarnation functions
            from bot.events import check_member_reincarnation, process_member_funeral
            from bot.models import DepartedMember
            from datetime import datetime, timezone
            
            # Check if user already has a departed member record
            existing_record = await self.bot.database.get_departed_member(user.id, interaction.guild.id)
            
            if not existing_record:
                # Create a test departed member record first
                from bot.events import generate_funeral_message
                
                # Get user's highest role
                highest_role = None
                member_roles = [r for r in user.roles if r != interaction.guild.default_role]
                if member_roles:
                    highest_role = max(member_roles, key=lambda r: r.position).name
                
                # Get user stats
                user_stats = await self.bot.database.get_user_stats(interaction.guild.id, user.id)
                total_points = 0
                if user_stats:
                    total_points = user_stats.get('total_points_earned', user_stats.get('points', 0))
                
                # Create test departed member record with proper timezone handling
                now_utc = datetime.now(timezone.utc)
                join_date_utc = user.joined_at
                if join_date_utc and join_date_utc.tzinfo is None:
                    join_date_utc = join_date_utc.replace(tzinfo=timezone.utc)
                
                departed_member = DepartedMember(
                    member_id=user.id,
                    guild_id=interaction.guild.id,
                    username=user.name,
                    display_name=user.display_name,
                    avatar_url=str(user.avatar.url) if user.avatar else None,
                    highest_role=highest_role,
                    total_points=total_points,
                    join_date=join_date_utc,
                    leave_date=now_utc,
                    times_left=1,
                    funeral_message=generate_funeral_message(user.display_name, highest_role, total_points, 1),
                    created_at=now_utc
                )
                
                # Save test record
                logger.info(f"🧪 Attempting to save test departed member record for {user.display_name}")
                success = await self.bot.database.save_departed_member(departed_member)
                if not success:
                    logger.error(f"❌ Failed to save departed member record for {user.display_name}")
                    embed = create_error_embed("Database Error", "Failed to create test departed member record. Check logs for details.")
                    await interaction.followup.send(embed=embed)
                    return
                logger.info(f"✅ Successfully saved test departed member record for {user.display_name}")
                
                embed = create_info_embed(
                    "Test Record Created", 
                    f"Created test departed member record for {user.display_name}",
                    "Now testing reincarnation notification..."
                )
                await interaction.followup.send(embed=embed)
            
            # Now test the reincarnation system
            await check_member_reincarnation(user, self.bot)
            
            embed = create_success_embed(
                "Reincarnation Test Complete",
                f"Successfully tested reincarnation system for {user.display_name}",
                "Check the reincarnation channel for the notification. If no notification appeared, check the logs for debugging information."
            )
            await interaction.followup.send(embed=embed)
            logger.info(f"🔄 Admin {interaction.user.display_name} tested reincarnation for {user.display_name}")
            
        except Exception as e:
            logger.error(f"❌ Error in test_reincarnation command: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            embed = create_error_embed("Test Failed", f"Error testing reincarnation: {str(e)}")
            await interaction.followup.send(embed=embed)


async def update_active_leaderboards(guild_id):
    """Update all active leaderboard views for a guild"""
    if not active_leaderboard_views:
        return
        
    views_to_update = []
    for view in active_leaderboard_views[:]:  # Create a copy to iterate safely
        if hasattr(view, 'guild_id') and view.guild_id == guild_id and hasattr(view, 'is_active') and view.is_active:
            views_to_update.append(view)
    
    if not views_to_update:
        logger.debug(f"🔄 No active leaderboard views to update for guild {guild_id}")
        return
    
    logger.debug(f"🔄 Updating {len(views_to_update)} leaderboard view(s) for guild {guild_id}")
    
    for view in views_to_update:
        try:
            await view.auto_update_leaderboard()
        except Exception as e:
            logger.debug(f"Non-critical error updating leaderboard view: {e}")
            # Don't remove views on error - they might recover
