from typing import List, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging
import json

from bot.sql_database import SQLDatabase
from bot.models import QuestRank, QuestCategory, QuestStatus

logger = logging.getLogger(__name__)

@dataclass
class TeamQuest:
    """Team quest data model"""
    quest_id: str
    team_size_required: int
    team_members: Set[int] = field(default_factory=set)
    team_leader: Optional[int] = None
    is_team_complete: bool = False
    team_formed_at: Optional[datetime] = None
    guild_id: int = 0

@dataclass
class TeamProgress:
    """Team quest progress tracking"""
    quest_id: str
    user_id: int
    guild_id: int
    team_role: str  # "leader" or "member"
    joined_team_at: datetime
    individual_progress: Dict[str, any] = field(default_factory=dict)

class TeamQuestManager:
    """Manages team-based quests with full database integration"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
        self.active_teams: Dict[str, TeamQuest] = {}
    
    async def initialize_database(self):
        """Initialize team quest tables"""
        await self.database.execute_query("""
            CREATE TABLE IF NOT EXISTS team_quests (
                quest_id VARCHAR(20) PRIMARY KEY,
                guild_id BIGINT NOT NULL,
                team_size_required INTEGER NOT NULL,
                team_leader BIGINT,
                is_team_complete BOOLEAN DEFAULT FALSE,
                team_formed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await self.database.execute_query("""
            CREATE TABLE IF NOT EXISTS team_progress (
                id SERIAL PRIMARY KEY,
                quest_id VARCHAR(20) NOT NULL,
                user_id BIGINT NOT NULL,
                guild_id BIGINT NOT NULL,
                team_role VARCHAR(10) NOT NULL CHECK (team_role IN ('leader', 'member')),
                joined_team_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                individual_progress JSONB DEFAULT '{}',
                UNIQUE(quest_id, user_id)
            )
        """)
        
        # Create indexes for performance
        await self.database.execute_query("CREATE INDEX IF NOT EXISTS idx_team_quests_guild ON team_quests(guild_id)")
        await self.database.execute_query("CREATE INDEX IF NOT EXISTS idx_team_progress_quest ON team_progress(quest_id)")
        await self.database.execute_query("CREATE INDEX IF NOT EXISTS idx_team_progress_user ON team_progress(user_id, guild_id)")
        
        logger.info("✅ Team quest database tables initialized")
    
    async def create_team_quest(self, quest_id: str, team_size: int, leader_id: Optional[int], guild_id: int) -> TeamQuest:
        """Create a new team for a quest"""
        # Check if team already exists
        existing = await self.get_team_status(quest_id)
        if existing:
            raise ValueError("Team already exists for this quest")
        
        # Create team quest
        team_quest = TeamQuest(
            quest_id=quest_id,
            team_size_required=team_size,
            team_members=set() if leader_id is None else {leader_id},
            team_leader=leader_id,
            team_formed_at=datetime.now(),
            guild_id=guild_id
        )
        
        # Save to database
        await self.database.execute_query("""
            INSERT INTO team_quests (quest_id, guild_id, team_size_required, team_leader, team_formed_at)
            VALUES ($1, $2, $3, $4, $5)
        """, quest_id, guild_id, team_size, leader_id, datetime.now())
        
        # Save team leader progress only if leader_id is provided
        if leader_id is not None:
            await self._save_team_progress(TeamProgress(
                quest_id=quest_id,
                user_id=leader_id,
                guild_id=guild_id,
                team_role="leader",
                joined_team_at=datetime.now()
            ))
        
        self.active_teams[quest_id] = team_quest
        logger.info(f"✅ Created team quest {quest_id} with leader {leader_id}")
        
        return team_quest
    
    async def join_team(self, quest_id: str, user_id: int, guild_id: int) -> Tuple[bool, str]:
        """Join a team for a quest"""
        team = await self.get_team_status(quest_id)
        
        if not team:
            return False, "No team found for this quest"
        
        if len(team.team_members) >= team.team_size_required:
            return False, "Team is already full"
        
        if user_id in team.team_members:
            return False, "You are already in this team"
        
        # Check if user is already in another team for the same quest
        async with self.database.pool.acquire() as conn:
            existing_progress = await conn.fetchrow("""
                SELECT quest_id FROM team_progress 
                WHERE user_id = $1 AND guild_id = $2 AND quest_id = $3
            """, user_id, guild_id, quest_id)
        
        if existing_progress:
            return False, "You are already in a team for this quest"
        
        # Add member to team
        team.team_members.add(user_id)
        
        # If this is the first member and no leader exists, make them the leader
        team_role = "member"
        if team.team_leader is None and len(team.team_members) == 1:
            team.team_leader = user_id
            team_role = "leader"
            # Update leader in database
            await self.database.execute_query("""
                UPDATE team_quests SET team_leader = $1 WHERE quest_id = $2
            """, user_id, quest_id)
        
        # Check if team is now complete
        if len(team.team_members) == team.team_size_required:
            team.is_team_complete = True
            await self.database.execute_query("""
                UPDATE team_quests SET is_team_complete = TRUE WHERE quest_id = $1
            """, quest_id)
        
        # Save team member progress
        await self._save_team_progress(TeamProgress(
            quest_id=quest_id,
            user_id=user_id,
            guild_id=guild_id,
            team_role=team_role,
            joined_team_at=datetime.now()
        ))
        
        logger.info(f"✅ User {user_id} joined team for quest {quest_id}")
        return True, "Successfully joined the team!"
    
    async def leave_team(self, quest_id: str, user_id: int, guild_id: int) -> Tuple[bool, str]:
        """Leave a team quest"""
        team = await self.get_team_status(quest_id)
        
        if not team:
            return False, "No team found for this quest"
        
        if user_id not in team.team_members:
            return False, "You are not in this team"
        
        # If leader is leaving, disband the team
        if user_id == team.team_leader:
            await self._disband_team(quest_id)
            return True, "Team disbanded as leader left"
        
        # Remove member from team
        team.team_members.remove(user_id)
        team.is_team_complete = False
        
        # Update database
        await self.database.execute_query("DELETE FROM team_progress WHERE quest_id = $1 AND user_id = $2", quest_id, user_id)
        await self.database.execute_query("UPDATE team_quests SET is_team_complete = FALSE WHERE quest_id = $1", quest_id)
        
        logger.info(f"✅ User {user_id} left team for quest {quest_id}")
        return True, "Successfully left the team"
    
    async def get_team_status(self, quest_id: str) -> Optional[TeamQuest]:
        """Get team status for a quest"""
        if quest_id in self.active_teams:
            return self.active_teams[quest_id]
        
        # Load from database
        async with self.database.pool.acquire() as conn:
            team_data = await conn.fetchrow("""
                SELECT * FROM team_quests WHERE quest_id = $1
            """, quest_id)
        
        if not team_data:
            return None
        
        # Get team members
        async with self.database.pool.acquire() as conn:
            members = await conn.fetch("""
                SELECT user_id FROM team_progress WHERE quest_id = $1
            """, quest_id)
        
        team_members = {row['user_id'] for row in members}
        
        team = TeamQuest(
            quest_id=quest_id,
            team_size_required=team_data['team_size_required'],
            team_members=team_members,
            team_leader=team_data['team_leader'],
            is_team_complete=team_data['is_team_complete'],
            team_formed_at=team_data['team_formed_at'],
            guild_id=team_data['guild_id']
        )
        
        self.active_teams[quest_id] = team
        return team
    
    async def is_team_complete(self, quest_id: str) -> bool:
        """Check if team is complete for a quest"""
        team = await self.get_team_status(quest_id)
        return team.is_team_complete if team else False
    
    async def get_team_members(self, quest_id: str) -> List[int]:
        """Get list of team members"""
        team = await self.get_team_status(quest_id)
        return list(team.team_members) if team else []
    
    async def get_user_teams(self, user_id: int, guild_id: int) -> List[str]:
        """Get all teams a user is part of"""
        async with self.database.pool.acquire() as conn:
            teams = await conn.fetch("""
                SELECT quest_id FROM team_progress 
                WHERE user_id = $1 AND guild_id = $2
            """, user_id, guild_id)
        
        return [row['quest_id'] for row in teams]
    
    async def get_available_teams(self, guild_id: int) -> List[TeamQuest]:
        """Get all available teams that need more members"""
        async with self.database.pool.acquire() as conn:
            teams_data = await conn.fetch("""
                SELECT * FROM team_quests 
                WHERE guild_id = $1 AND is_team_complete = FALSE
                ORDER BY team_formed_at DESC
            """, guild_id)
        
        teams = []
        for team_data in teams_data:
            team = await self.get_team_status(team_data['quest_id'])
            if team and len(team.team_members) < team.team_size_required:
                teams.append(team)
        
        return teams
    
    async def _save_team_progress(self, progress: TeamProgress):
        """Save team progress to database"""
        await self.database.execute_query("""
            INSERT INTO team_progress (quest_id, user_id, guild_id, team_role, joined_team_at, individual_progress)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (quest_id, user_id) DO UPDATE SET
                team_role = EXCLUDED.team_role,
                joined_team_at = EXCLUDED.joined_team_at
        """, progress.quest_id, progress.user_id, progress.guild_id, progress.team_role, 
            progress.joined_team_at, json.dumps(progress.individual_progress))
    
    async def _disband_team(self, quest_id: str):
        """Disband a team completely"""
        await self.database.execute_query("DELETE FROM team_progress WHERE quest_id = $1", quest_id)
        await self.database.execute_query("DELETE FROM team_quests WHERE quest_id = $1", quest_id)
        
        if quest_id in self.active_teams:
            del self.active_teams[quest_id]
        
        logger.info(f"✅ Disbanded team for quest {quest_id}")
    
    async def update_individual_progress(self, quest_id: str, user_id: int, progress_data: Dict[str, any]):
        """Update individual member's progress within the team"""
        await self.database.execute_query("""
            UPDATE team_progress 
            SET individual_progress = $1 
            WHERE quest_id = $2 AND user_id = $3
        """, json.dumps(progress_data), quest_id, user_id)
    
    async def get_team_progress_summary(self, quest_id: str) -> List[Dict]:
        """Get progress summary for all team members"""
        async with self.database.pool.acquire() as conn:
            progress_data = await conn.fetch("""
                SELECT user_id, team_role, individual_progress, joined_team_at 
                FROM team_progress WHERE quest_id = $1
                ORDER BY team_role DESC, joined_team_at ASC
            """, quest_id)
        
        return [dict(row) for row in progress_data]