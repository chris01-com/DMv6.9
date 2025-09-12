import logging
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime
import discord
from discord import app_commands
from bot.models import Quest, QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

class QuestEditingSystem:
    """System for quest creators to edit and modify their active quests"""
    
    def __init__(self, database, quest_manager, notification_system):
        self.database = database
        self.quest_manager = quest_manager
        self.notification_system = notification_system
    
    async def initialize_editing_system(self):
        """Initialize quest editing system"""
        try:
            async with self.database.pool.acquire() as conn:
                # Quest edit history table
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS quest_edit_history (
                        id SERIAL PRIMARY KEY,
                        quest_id VARCHAR(50) NOT NULL,
                        editor_id BIGINT NOT NULL,
                        field_changed VARCHAR(50) NOT NULL,
                        old_value TEXT,
                        new_value TEXT,
                        edit_reason TEXT,
                        edited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        requires_approval BOOLEAN DEFAULT FALSE,
                        approved_by BIGINT,
                        approved_at TIMESTAMP
                    )
                ''')
                
                # Pending quest edits (for approval workflow)
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS pending_quest_edits (
                        id SERIAL PRIMARY KEY,
                        quest_id VARCHAR(50) NOT NULL,
                        editor_id BIGINT NOT NULL,
                        field_name VARCHAR(50) NOT NULL,
                        current_value TEXT,
                        proposed_value TEXT,
                        edit_reason TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status VARCHAR(20) DEFAULT 'pending'
                    )
                ''')
                
            logger.info("✅ Quest editing system initialized")
            
        except Exception as e:
            logger.error(f"❌ Error initializing quest editing: {e}")
    
    async def can_edit_quest(self, quest_id: str, user_id: int, guild_id: int, user_permissions: discord.Permissions) -> Tuple[bool, str]:
        """Check if user can edit this quest"""
        try:
            quest = await self.quest_manager.get_quest(quest_id)
            if not quest:
                return False, "Quest not found"
            
            if quest.guild_id != guild_id:
                return False, "Quest not from this server"
            
            # Quest creator can always edit their own quests
            if quest.creator_id == user_id:
                return True, "Quest creator"
            
            # Admins and moderators can edit any quest
            if user_permissions.administrator or user_permissions.manage_guild:
                return True, "Administrator privileges"
            
            return False, "Only the quest creator or administrators can edit quests"
            
        except Exception as e:
            logger.error(f"❌ Error checking edit permissions: {e}")
            return False, "Permission check failed"
    
    async def edit_quest_field(self, quest_id: str, editor_id: int, field_name: str, 
                              new_value: Any, reason: str = "") -> Tuple[bool, str]:
        """Edit a specific field of a quest"""
        try:
            quest = await self.quest_manager.get_quest(quest_id)
            if not quest:
                return False, "Quest not found"
            
            # Get current value
            current_value = getattr(quest, field_name, None)
            if current_value == new_value:
                return False, "No change in value"
            
            # Determine if edit requires approval
            requires_approval = self._requires_approval(field_name, current_value, new_value)
            
            if requires_approval:
                # Create pending edit for approval
                return await self._create_pending_edit(quest_id, editor_id, field_name, 
                                                     str(current_value), str(new_value), reason)
            else:
                # Apply edit immediately
                return await self._apply_edit_immediately(quest, field_name, new_value, editor_id, reason)
                
        except Exception as e:
            logger.error(f"❌ Error editing quest field: {e}")
            return False, f"Edit failed: {str(e)}"
    
    async def edit_quest_multiple_fields(self, quest_id: str, editor_id: int, 
                                       changes: Dict[str, Any], reason: str = "") -> Tuple[bool, str, List[str]]:
        """Edit multiple fields of a quest at once"""
        try:
            quest = await self.quest_manager.get_quest(quest_id)
            if not quest:
                return False, "Quest not found", []
            
            immediate_changes = {}
            pending_changes = {}
            
            # Categorize changes by approval requirement
            for field_name, new_value in changes.items():
                current_value = getattr(quest, field_name, None)
                if current_value != new_value:
                    if self._requires_approval(field_name, current_value, new_value):
                        pending_changes[field_name] = new_value
                    else:
                        immediate_changes[field_name] = new_value
            
            messages = []
            
            # Apply immediate changes
            if immediate_changes:
                for field_name, new_value in immediate_changes.items():
                    success, msg = await self._apply_edit_immediately(quest, field_name, new_value, editor_id, reason)
                    if success:
                        messages.append(f"✅ {field_name} updated immediately")
                    else:
                        messages.append(f"❌ {field_name} update failed: {msg}")
            
            # Create pending edits for approval-required changes
            if pending_changes:
                for field_name, new_value in pending_changes.items():
                    current_value = getattr(quest, field_name, None)
                    await self._create_pending_edit(quest_id, editor_id, field_name, 
                                                  str(current_value), str(new_value), reason)
                    messages.append(f"⏳ {field_name} change submitted for approval")
            
            success = len(messages) > 0
            summary = f"Processed {len(changes)} field changes"
            return success, summary, messages
            
        except Exception as e:
            logger.error(f"❌ Error editing multiple quest fields: {e}")
            return False, f"Bulk edit failed: {str(e)}", []
    
    async def _apply_edit_immediately(self, quest: Quest, field_name: str, new_value: Any, 
                                    editor_id: int, reason: str) -> Tuple[bool, str]:
        """Apply an edit immediately without approval"""
        try:
            current_value = getattr(quest, field_name, None)
            
            # Update the quest object
            setattr(quest, field_name, new_value)
            
            # Save to database
            await self.database.save_quest(quest)
            
            # Record edit history
            await self._record_edit_history(quest.quest_id, editor_id, field_name, 
                                          str(current_value), str(new_value), reason)
            
            # Notify users who accepted this quest about the change
            await self._notify_quest_participants(quest.quest_id, field_name, 
                                                str(current_value), str(new_value), editor_id)
            
            logger.info(f"✅ Quest {quest.quest_id} field '{field_name}' updated by {editor_id}")
            return True, f"{field_name} updated successfully"
            
        except Exception as e:
            logger.error(f"❌ Error applying immediate edit: {e}")
            return False, f"Failed to apply edit: {str(e)}"
    
    async def _create_pending_edit(self, quest_id: str, editor_id: int, field_name: str, 
                                 current_value: str, proposed_value: str, reason: str) -> Tuple[bool, str]:
        """Create a pending edit for approval"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO pending_quest_edits 
                    (quest_id, editor_id, field_name, current_value, proposed_value, edit_reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', quest_id, editor_id, field_name, current_value, proposed_value, reason)
            
            logger.info(f"⏳ Pending edit created for quest {quest_id} field '{field_name}' by {editor_id}")
            return True, f"{field_name} change submitted for admin approval"
            
        except Exception as e:
            logger.error(f"❌ Error creating pending edit: {e}")
            return False, f"Failed to submit edit for approval: {str(e)}"
    
    def _requires_approval(self, field_name: str, old_value: Any, new_value: Any) -> bool:
        """Determine if a field change requires admin approval"""
        # Major changes that affect quest difficulty or rewards require approval
        approval_required_fields = {'reward', 'rank', 'requirements'}
        
        if field_name in approval_required_fields:
            return True
        
        # Large changes in description might require approval
        if field_name == 'description':
            if len(str(new_value)) > len(str(old_value)) * 2:
                return True
        
        return False
    
    async def _record_edit_history(self, quest_id: str, editor_id: int, field_name: str, 
                                 old_value: str, new_value: str, reason: str):
        """Record edit in history"""
        try:
            async with self.database.pool.acquire() as conn:
                await conn.execute('''
                    INSERT INTO quest_edit_history 
                    (quest_id, editor_id, field_changed, old_value, new_value, edit_reason)
                    VALUES ($1, $2, $3, $4, $5, $6)
                ''', quest_id, editor_id, field_name, old_value, new_value, reason)
                
        except Exception as e:
            logger.error(f"❌ Error recording edit history: {e}")
    
    async def _notify_quest_participants(self, quest_id: str, field_name: str, 
                                       old_value: str, new_value: str, editor_id: int):
        """Notify users who accepted this quest about changes"""
        try:
            # Get users who have accepted this quest
            async with self.database.pool.acquire() as conn:
                participants = await conn.fetch('''
                    SELECT DISTINCT qp.user_id, qp.guild_id, q.title
                    FROM quest_progress qp
                    JOIN quests q ON qp.quest_id = q.quest_id
                    WHERE qp.quest_id = $1 AND qp.status IN ('accepted', 'completed')
                ''', quest_id)
            
            # Send notifications to participants
            for participant in participants:
                if participant['user_id'] != editor_id:  # Don't notify the editor
                    title = f"Quest Updated: {participant['title']}"
                    content = (f"The quest **{participant['title']}** (`{quest_id}`) has been updated.\n\n"
                             f"**Changed:** {field_name.title()}\n"
                             f"**Before:** {old_value[:100]}{'...' if len(old_value) > 100 else ''}\n"
                             f"**After:** {new_value[:100]}{'...' if len(new_value) > 100 else ''}\n\n"
                             f"*Updated by <@{editor_id}>*")
                    
                    await self.notification_system.queue_notification(
                        user_id=participant['user_id'],
                        guild_id=participant['guild_id'],
                        notification_type='quest_updated',
                        title=title,
                        content=content,
                        priority='normal'
                    )
                    
        except Exception as e:
            logger.error(f"❌ Error notifying quest participants: {e}")
    
    async def get_edit_history(self, quest_id: str, limit: int = 20) -> List[Dict]:
        """Get edit history for a quest"""
        try:
            async with self.database.pool.acquire() as conn:
                history = await conn.fetch('''
                    SELECT * FROM quest_edit_history 
                    WHERE quest_id = $1 
                    ORDER BY edited_at DESC 
                    LIMIT $2
                ''', quest_id, limit)
                
                return [dict(row) for row in history]
                
        except Exception as e:
            logger.error(f"❌ Error getting edit history: {e}")
            return []
    
    async def get_pending_edits(self, guild_id: int) -> List[Dict]:
        """Get pending edits for admin approval"""
        try:
            async with self.database.pool.acquire() as conn:
                pending = await conn.fetch('''
                    SELECT pe.*, q.title, q.creator_id
                    FROM pending_quest_edits pe
                    JOIN quests q ON pe.quest_id = q.quest_id
                    WHERE q.guild_id = $1 AND pe.status = 'pending'
                    ORDER BY pe.created_at ASC
                ''', guild_id)
                
                return [dict(row) for row in pending]
                
        except Exception as e:
            logger.error(f"❌ Error getting pending edits: {e}")
            return []
    
    async def approve_edit(self, edit_id: int, approver_id: int) -> Tuple[bool, str]:
        """Approve a pending quest edit"""
        try:
            async with self.database.pool.acquire() as conn:
                # Get the pending edit
                edit = await conn.fetchrow('''
                    SELECT * FROM pending_quest_edits WHERE id = $1 AND status = 'pending'
                ''', edit_id)
                
                if not edit:
                    return False, "Pending edit not found"
                
                # Apply the edit
                quest = await self.quest_manager.get_quest(edit['quest_id'])
                if not quest:
                    return False, "Quest not found"
                
                # Update the quest field
                setattr(quest, edit['field_name'], edit['proposed_value'])
                await self.database.save_quest(quest)
                
                # Record in history
                await self._record_edit_history(
                    edit['quest_id'], edit['editor_id'], edit['field_name'],
                    edit['current_value'], edit['proposed_value'], edit['edit_reason']
                )
                
                # Update pending edit status
                await conn.execute('''
                    UPDATE pending_quest_edits 
                    SET status = 'approved', approved_by = $1, approved_at = CURRENT_TIMESTAMP
                    WHERE id = $2
                ''', approver_id, edit_id)
                
                # Notify participants
                await self._notify_quest_participants(
                    edit['quest_id'], edit['field_name'],
                    edit['current_value'], edit['proposed_value'], edit['editor_id']
                )
                
                return True, f"Edit approved for quest {edit['quest_id']}"
                
        except Exception as e:
            logger.error(f"❌ Error approving edit: {e}")
            return False, f"Approval failed: {str(e)}"
    
    async def reject_edit(self, edit_id: int, approver_id: int, reason: str = "") -> Tuple[bool, str]:
        """Reject a pending quest edit"""
        try:
            async with self.database.pool.acquire() as conn:
                # Update pending edit status
                result = await conn.execute('''
                    UPDATE pending_quest_edits 
                    SET status = 'rejected', approved_by = $1, approved_at = CURRENT_TIMESTAMP
                    WHERE id = $2 AND status = 'pending'
                ''', approver_id, edit_id)
                
                if result == "UPDATE 0":
                    return False, "Pending edit not found"
                
                return True, f"Edit rejected{' - ' + reason if reason else ''}"
                
        except Exception as e:
            logger.error(f"❌ Error rejecting edit: {e}")
            return False, f"Rejection failed: {str(e)}"
    
    def create_edit_history_embed(self, quest_id: str, history: List[Dict]) -> discord.Embed:
        """Create embed showing quest edit history"""
        if not history:
            embed = discord.Embed(
                title=f"📝 Edit History: {quest_id}",
                description="No edit history for this quest.",
                color=discord.Color.light_grey()
            )
            return embed
        
        embed = discord.Embed(
            title=f"📝 Edit History: {quest_id}",
            description=f"Last {len(history)} changes to this quest:",
            color=discord.Color.blue()
        )
        
        for i, edit in enumerate(history, 1):
            field_name = edit['field_changed'].replace('_', ' ').title()
            old_val = edit['old_value'][:50] + ('...' if len(edit['old_value']) > 50 else '')
            new_val = edit['new_value'][:50] + ('...' if len(edit['new_value']) > 50 else '')
            
            embed.add_field(
                name=f"{i}. {field_name} Changed",
                value=(f"**Before:** {old_val}\n"
                      f"**After:** {new_val}\n"
                      f"*By <@{edit['editor_id']}> on {edit['edited_at'].strftime('%m/%d/%y %H:%M')}*"
                      f"{' - ' + edit['edit_reason'] if edit['edit_reason'] else ''}"),
                inline=False
            )
        
        embed.set_footer(text="Quest edit history shows recent changes")
        return embed
    
    def create_pending_edits_embed(self, pending_edits: List[Dict]) -> discord.Embed:
        """Create embed showing pending edits for approval"""
        if not pending_edits:
            embed = discord.Embed(
                title="⏳ Pending Quest Edits",
                description="No pending edits require approval.",
                color=discord.Color.green()
            )
            return embed
        
        embed = discord.Embed(
            title=f"⏳ Pending Quest Edits ({len(pending_edits)})",
            description="The following quest edits require admin approval:",
            color=discord.Color.orange()
        )
        
        for edit in pending_edits[:10]:  # Limit to 10 to avoid embed limits
            field_name = edit['field_name'].replace('_', ' ').title()
            current = edit['current_value'][:30] + ('...' if len(edit['current_value']) > 30 else '')
            proposed = edit['proposed_value'][:30] + ('...' if len(edit['proposed_value']) > 30 else '')
            
            embed.add_field(
                name=f"Quest: {edit['title']} ({edit['quest_id']})",
                value=(f"**Field:** {field_name}\n"
                      f"**Current:** {current}\n"
                      f"**Proposed:** {proposed}\n"
                      f"*By <@{edit['editor_id']}> • {edit['created_at'].strftime('%m/%d %H:%M')}*"
                      f"{' - ' + edit['edit_reason'][:50] if edit['edit_reason'] else ''}"),
                inline=False
            )
        
        if len(pending_edits) > 10:
            embed.add_field(
                name="And more...",
                value=f"+{len(pending_edits) - 10} additional pending edits",
                inline=False
            )
        
        embed.set_footer(text="Use /approve_edit <id> or /reject_edit <id> to process these")
        return embed