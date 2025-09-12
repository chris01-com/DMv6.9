from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import uuid
from bot.sql_database import SQLDatabase
from bot.models import Quest, QuestProgress, QuestRank, QuestStatus, ProgressStatus


class QuestManager:
    """Manages quest operations"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
    
    async def create_quest(self, title: str, description: str, creator_id: int, guild_id: int,
                          requirements: str = "", reward: str = "", rank: str = QuestRank.NORMAL,
                          category: str = "other", required_role_ids: Optional[List[int]] = None) -> Quest:
        """Create a new quest"""
        if required_role_ids is None:
            required_role_ids = []
        
        quest_id = str(uuid.uuid4())[:8]
        
        quest = Quest(
            quest_id=quest_id,
            title=title,
            description=description,
            creator_id=creator_id,
            guild_id=guild_id,
            requirements=requirements,
            reward=reward,
            rank=rank,
            category=category,
            status=QuestStatus.AVAILABLE,
            created_at=datetime.now(),
            required_role_ids=required_role_ids
        )
        
        await self.database.save_quest(quest)
        return quest
    
    async def get_quest(self, quest_id: str) -> Optional[Quest]:
        """Get a quest by ID"""
        return await self.database.get_quest(quest_id)
    
    async def get_available_quests(self, guild_id: int) -> List[Quest]:
        """Get all available quests for a guild"""
        return await self.database.get_guild_quests(guild_id, QuestStatus.AVAILABLE)
    
    async def get_guild_quests(self, guild_id: int) -> List[Quest]:
        """Get all quests for a guild"""
        return await self.database.get_guild_quests(guild_id)
    
    async def get_pending_approvals(self, guild_id: int) -> List[dict]:
        """Get all quest submissions pending approval"""
        return await self.database.get_pending_quest_approvals(guild_id)
    
    async def accept_quest(self, quest_id: str, user_id: int, user_role_ids: List[int], 
                          channel_id: int) -> Tuple[Optional[QuestProgress], Optional[str]]:
        """Accept a quest"""
        quest = await self.get_quest(quest_id)
        if not quest:
            return None, "Quest not found!"
        
        if quest.status != QuestStatus.AVAILABLE:
            return None, "Quest is not available for acceptance!"
        
        # Check if user already has this quest
        existing_progress = await self.database.get_user_quest_progress(user_id, quest_id)
        if existing_progress:
            if existing_progress.status in [ProgressStatus.ACCEPTED, ProgressStatus.COMPLETED]:
                return None, "You have already accepted this quest!"
            elif existing_progress.status == ProgressStatus.REJECTED:
                # Special handling for starter quests - check if rejection was in current membership period
                if quest_id.startswith('starter'):
                    async with self.database.pool.acquire() as conn:
                        # Check if user has a departure record
                        departed_record = await conn.fetchrow('''
                            SELECT leave_date FROM departed_members 
                            WHERE member_id = $1 AND guild_id = $2 
                            ORDER BY leave_date DESC 
                            LIMIT 1
                        ''', user_id, quest.guild_id)
                        
                        if departed_record and existing_progress.completed_at:
                            # If they left after the rejection, they can try again in new membership
                            if departed_record['leave_date'] > existing_progress.completed_at:
                                # Allow retry since they rejoined after the rejection
                                pass
                            else:
                                return None, "Starter quests can only be attempted once per membership period."
                        else:
                            return None, "Starter quests can only be attempted once per membership period."
                
                # Check if 24 hours have passed since rejection for regular quests
                if existing_progress.completed_at:
                    time_since_rejection = datetime.now() - existing_progress.completed_at
                    if time_since_rejection < timedelta(hours=24):
                        hours_left = 24 - int(time_since_rejection.total_seconds() / 3600)
                        return None, f"You must wait {hours_left} more hours before attempting this quest again!"
        
        # Additional check: For starter quests, check if user has completed them in current membership period
        if quest_id.startswith('starter'):
            async with self.database.pool.acquire() as conn:
                # Check if user has a departure record (meaning they left and rejoined)
                departed_record = await conn.fetchrow('''
                    SELECT leave_date FROM departed_members 
                    WHERE member_id = $1 AND guild_id = $2 
                    ORDER BY leave_date DESC 
                    LIMIT 1
                ''', user_id, quest.guild_id)
                
                if departed_record:
                    # User has left and rejoined - check if they completed starter quest after their last return
                    last_leave_date = departed_record['leave_date']
                    completed_after_return = await conn.fetchrow('''
                        SELECT quest_id FROM quest_progress 
                        WHERE user_id = $1 AND quest_id = $2 AND status = 'approved'
                        AND completed_at > $3
                    ''', user_id, quest_id, last_leave_date)
                    
                    if completed_after_return:
                        return None, "You have already completed this starter quest in your current membership period. Starter quests can only be completed once per server membership."
                else:
                    # User has never left - check if they ever completed this starter quest
                    completed_before = await conn.fetchrow('''
                        SELECT quest_id FROM quest_progress 
                        WHERE user_id = $1 AND quest_id = $2 AND status = 'approved'
                    ''', user_id, quest_id)
                    
                    if completed_before:
                        return None, "You have already completed this starter quest. Starter quests can only be completed once per membership period."
        
        # Check role requirements
        if quest.required_role_ids:
            if not any(role_id in user_role_ids for role_id in quest.required_role_ids):
                return None, "You don't have the required roles for this quest!"
        
        # Check starter quest requirements - only for mentorless users who have starter quests assigned
        if not quest_id.startswith('starter'):
            async with self.database.pool.acquire() as conn:
                # First check if this user has starter quests assigned through welcome automation
                welcome_record = await conn.fetchrow('''
                    SELECT starter_quest_1, starter_quest_2, mentor_id FROM welcome_automation 
                    WHERE user_id = $1 AND guild_id = $2
                ''', user_id, quest.guild_id)
                
                # Only enforce starter quest requirements if user has them assigned AND no mentor
                if welcome_record and (welcome_record['starter_quest_1'] or welcome_record['starter_quest_2']):
                    # Skip starter quest requirements if user has a mentor
                    if welcome_record['mentor_id'] is not None:
                        # User has a mentor, skip starter quest requirement
                        pass
                    else:
                        # User is mentorless, enforce starter quest completion
                        # Check if user has completed both assigned starter quests
                        starter_completions = await conn.fetch('''
                            SELECT quest_id FROM quest_progress 
                            WHERE user_id = $1 AND guild_id = $2 
                            AND quest_id IN ('starter1', 'starter2', 'starter3', 'starter4', 'starter5') 
                            AND status = 'approved'
                        ''', user_id, quest.guild_id)
                        
                        completed_starter_ids = [row['quest_id'] for row in starter_completions]
                        
                        # Check any assigned starter quests dynamically
                        assigned_starter_quests = []
                        if welcome_record['starter_quest_1']:
                            assigned_starter_quests.append(welcome_record['starter_quest_1'])
                        if welcome_record['starter_quest_2']:
                            assigned_starter_quests.append(welcome_record['starter_quest_2'])
                        
                        # Check if all assigned starter quests are completed
                        for starter_quest_id in assigned_starter_quests:
                            if starter_quest_id not in completed_starter_ids:
                                return None, f"You must complete the {starter_quest_id} quest before accepting other quests!"
        
        # Create progress entry
        progress = QuestProgress(
            quest_id=quest_id,
            user_id=user_id,
            guild_id=quest.guild_id,
            status=ProgressStatus.ACCEPTED,
            accepted_at=datetime.now(),
            channel_id=channel_id
        )
        
        await self.database.save_quest_progress(progress)
        return progress, None
    
    async def complete_quest(self, quest_id: str, user_id: int, proof_text: str, 
                           proof_image_urls: List[str]) -> Optional[QuestProgress]:
        """Complete a quest (submit proof)"""
        progress = await self.database.get_user_quest_progress(user_id, quest_id)
        if not progress or progress.status not in [ProgressStatus.ACCEPTED, ProgressStatus.ASSIGNED]:
            return None
        
        # If quest was assigned, auto-accept it when submitting
        if progress.status == ProgressStatus.ASSIGNED:
            progress.status = ProgressStatus.ACCEPTED
            progress.accepted_at = datetime.now()
            await self.database.save_quest_progress(progress)
        
        progress.status = ProgressStatus.COMPLETED
        progress.completed_at = datetime.now()
        progress.proof_text = proof_text
        progress.proof_image_urls = proof_image_urls
        
        await self.database.save_quest_progress(progress)
        return progress
    
    async def approve_quest(self, quest_id: str, user_id: int, approver_id: int) -> Optional[QuestProgress]:
        """Approve a completed quest"""
        progress = await self.database.get_user_quest_progress(user_id, quest_id)
        if not progress or progress.status != ProgressStatus.COMPLETED:
            return None
        
        progress.status = ProgressStatus.APPROVED
        progress.approved_at = datetime.now()
        progress.approval_status = f"Approved by {approver_id}"
        
        await self.database.save_quest_progress(progress)
        return progress
    
    async def reject_quest(self, quest_id: str, user_id: int, approver_id: int, reason: str = "") -> Optional[QuestProgress]:
        """Reject a completed quest"""
        progress = await self.database.get_user_quest_progress(user_id, quest_id)
        if not progress or progress.status != ProgressStatus.COMPLETED:
            return None
        
        progress.status = ProgressStatus.REJECTED
        progress.approved_at = datetime.now()
        progress.approval_status = f"Rejected by {approver_id}: {reason}"
        
        await self.database.save_quest_progress(progress)
        return progress
    
    async def get_user_quests(self, user_id: int, guild_id: int, status: str = None) -> List[QuestProgress]:
        """Get all quests for a user, optionally filtered by status"""
        async with self.database.pool.acquire() as conn:
            if status:
                rows = await conn.fetch('''
                    SELECT * FROM quest_progress 
                    WHERE user_id = $1 AND guild_id = $2 AND status = $3
                    ORDER BY accepted_at DESC
                ''', user_id, guild_id, status)
            else:
                rows = await conn.fetch('''
                    SELECT * FROM quest_progress 
                    WHERE user_id = $1 AND guild_id = $2
                    ORDER BY accepted_at DESC
                ''', user_id, guild_id)
            
            progress_list = []
            for row in rows:
                progress = QuestProgress(
                    quest_id=row['quest_id'],
                    user_id=row['user_id'],
                    guild_id=row['guild_id'],
                    status=row['status'],
                    accepted_at=row['accepted_at'],
                    completed_at=row['completed_at'],
                    approved_at=row['approved_at'],
                    proof_text=row['proof_text'] or '',
                    proof_image_urls=list(row['proof_image_urls']) if row['proof_image_urls'] else [],
                    approval_status=row['approval_status'] or '',
                    channel_id=row['channel_id']
                )
                progress_list.append(progress)
                
            # Also check for assigned starter quests from welcome automation that may not be in quest_progress yet
            welcome_record = await conn.fetchrow('''
                SELECT starter_quest_1, starter_quest_2 FROM welcome_automation 
                WHERE user_id = $1 AND guild_id = $2
            ''', user_id, guild_id)
            
            if welcome_record:
                existing_quest_ids = {progress.quest_id for progress in progress_list}
                starter_quest_ids = []
                
                if welcome_record['starter_quest_1'] and welcome_record['starter_quest_1'] not in existing_quest_ids:
                    starter_quest_ids.append(welcome_record['starter_quest_1'])
                if welcome_record['starter_quest_2'] and welcome_record['starter_quest_2'] not in existing_quest_ids:
                    starter_quest_ids.append(welcome_record['starter_quest_2'])
                
                # Get quest details and create progress entries for missing starter quests
                for starter_id in starter_quest_ids:
                    quest_details = await conn.fetchrow('''
                        SELECT quest_id, title FROM quests 
                        WHERE guild_id = $1 AND quest_id = $2 AND status = 'available'
                    ''', guild_id, starter_id)
                    
                    if quest_details:
                        # Create a temporary progress entry to show in the list
                        starter_progress = QuestProgress(
                            quest_id=quest_details['quest_id'],
                            user_id=user_id,
                            guild_id=guild_id,
                            status=ProgressStatus.ASSIGNED,  # Special status for assigned but not accepted
                            accepted_at=datetime.now(),  # Use current time for assigned quests
                            completed_at=None,
                            approved_at=None,
                            proof_text='',
                            proof_image_urls=[],
                            approval_status='Starter quest assigned - use /accept_quest to begin',
                            channel_id=0
                        )
                        progress_list.append(starter_progress)
                        
            return progress_list
    
    async def delete_quest(self, quest_id: str) -> bool:
        """Delete a quest and all associated progress"""
        try:
            async with self.database.pool.acquire() as conn:
                # Delete quest progress first (foreign key constraint)
                await conn.execute('DELETE FROM quest_progress WHERE quest_id = $1', quest_id)
                # Delete the quest
                result = await conn.execute('DELETE FROM quests WHERE quest_id = $1', quest_id)
                return result != 'DELETE 0'
        except Exception:
            return False
    
    async def update_quest(self, quest: Quest) -> bool:
        """Update an existing quest"""
        try:
            await self.database.save_quest(quest)
            return True
        except Exception:
            return False
    
    async def get_completed_quests_for_approval(self, guild_id: int) -> List[Tuple[Quest, QuestProgress]]:
        """Get all completed quests awaiting approval"""
        async with self.database.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT q.*, qp.* FROM quests q
                JOIN quest_progress qp ON q.quest_id = qp.quest_id
                WHERE q.guild_id = $1 AND qp.status = $2
                ORDER BY qp.completed_at ASC
            ''', guild_id, ProgressStatus.COMPLETED)
            
            results = []
            for row in rows:
                quest = Quest(
                    quest_id=row['quest_id'],
                    title=row['title'],
                    description=row['description'],
                    creator_id=row['creator_id'],
                    guild_id=row['guild_id'],
                    requirements=row['requirements'] or '',
                    reward=row['reward'] or '',
                    rank=row['rank'] or 'normal',
                    category=row['category'] or 'other',
                    status=row['status'] or 'available',
                    created_at=row['created_at'],
                    required_role_ids=list(row['required_role_ids']) if row['required_role_ids'] else []
                )
                
                progress = QuestProgress(
                    quest_id=row['quest_id'],
                    user_id=row['user_id'],
                    guild_id=row['guild_id'],
                    status=row['status'],
                    accepted_at=row['accepted_at'],
                    completed_at=row['completed_at'],
                    approved_at=row['approved_at'],
                    proof_text=row['proof_text'] or '',
                    proof_image_urls=list(row['proof_image_urls']) if row['proof_image_urls'] else [],
                    approval_status=row['approval_status'] or '',
                    channel_id=row['channel_id']
                )
                
                results.append((quest, progress))
            return results