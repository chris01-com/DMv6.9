from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


class QuestRank:
    """Quest difficulty ranks"""
    EASY = "easy"
    NORMAL = "normal"
    MEDIUM = "medium"
    HARD = "hard"
    IMPOSSIBLE = "impossible"


class QuestCategory:
    """Quest categories"""
    HUNTING = "hunting"
    GATHERING = "gathering"
    COLLECTING = "collecting"
    CRAFTING = "crafting"
    EXPLORATION = "exploration"
    COMBAT = "combat"
    SOCIAL = "social"
    BUILDING = "building"
    TRADING = "trading"
    PUZZLE = "puzzle"
    SURVIVAL = "survival"
    TEAM = "team"
    OTHER = "other"


class QuestStatus:
    """Quest status values"""
    AVAILABLE = "available"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ProgressStatus:
    """Quest progress status values"""
    ASSIGNED = "assigned"  # Starter quest assigned but not yet accepted
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class Quest:
    """Quest data model"""
    quest_id: str
    title: str
    description: str
    creator_id: int
    guild_id: int
    requirements: str = ""
    reward: str = ""
    rank: str = QuestRank.NORMAL
    category: str = QuestCategory.OTHER
    status: str = QuestStatus.AVAILABLE
    created_at: datetime = field(default_factory=datetime.now)
    required_role_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "quest_id": self.quest_id,
            "title": self.title,
            "description": self.description,
            "creator_id": self.creator_id,
            "guild_id": self.guild_id,
            "requirements": self.requirements,
            "reward": self.reward,
            "rank": self.rank,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "required_role_ids": self.required_role_ids
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Quest':
        """Create from dictionary"""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not isinstance(created_at, datetime):
            created_at = datetime.now()

        return cls(
            quest_id=data["quest_id"],
            title=data["title"],
            description=data["description"],
            creator_id=data["creator_id"],
            guild_id=data["guild_id"],
            requirements=data.get("requirements", ""),
            reward=data.get("reward", ""),
            rank=data.get("rank", QuestRank.NORMAL),
            category=data.get("category", QuestCategory.OTHER),
            status=data.get("status", QuestStatus.AVAILABLE),
            created_at=created_at,
            required_role_ids=data.get("required_role_ids", [])
        )


@dataclass
class QuestProgress:
    """Quest progress data model"""
    quest_id: str
    user_id: int
    guild_id: int
    status: str
    accepted_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    proof_text: str = ""
    proof_image_urls: List[str] = field(default_factory=list)
    approval_status: str = ""
    channel_id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "quest_id": self.quest_id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "status": self.status,
            "accepted_at": self.accepted_at.isoformat() if isinstance(self.accepted_at, datetime) else self.accepted_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at and isinstance(self.completed_at, datetime) else self.completed_at,
            "approved_at": self.approved_at.isoformat() if self.approved_at and isinstance(self.approved_at, datetime) else self.approved_at,
            "proof_text": self.proof_text,
            "proof_image_urls": self.proof_image_urls,
            "approval_status": self.approval_status,
            "channel_id": self.channel_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'QuestProgress':
        """Create from dictionary"""
        def parse_datetime(dt_str):
            if dt_str and isinstance(dt_str, str):
                return datetime.fromisoformat(dt_str)
            elif isinstance(dt_str, datetime):
                return dt_str
            return None

        return cls(
            quest_id=data["quest_id"],
            user_id=data["user_id"],
            guild_id=data["guild_id"],
            status=data["status"],
            accepted_at=parse_datetime(data.get("accepted_at")) or datetime.now(),
            completed_at=parse_datetime(data.get("completed_at")),
            approved_at=parse_datetime(data.get("approved_at")),
            proof_text=data.get("proof_text", ""),
            proof_image_urls=data.get("proof_image_urls", []),
            approval_status=data.get("approval_status", ""),
            channel_id=data.get("channel_id")
        )


@dataclass
class UserStats:
    """User statistics data model (combines quest stats and leaderboard data)"""
    user_id: int
    guild_id: int
    quests_completed: int = 0
    quests_accepted: int = 0
    quests_rejected: int = 0
    last_updated: datetime = field(default_factory=datetime.now)
    # Additional leaderboard fields
    points: int = 0
    username: str = ""
    # Profile customization fields
    custom_title: str = ""
    status_message: str = ""
    preferred_color: str = "#2C3E50"
    notification_dm: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "quests_completed": self.quests_completed,
            "quests_accepted": self.quests_accepted,
            "quests_rejected": self.quests_rejected,
            "last_updated": self.last_updated.isoformat() if isinstance(self.last_updated, datetime) else self.last_updated,
            "points": self.points,
            "username": self.username,
            "custom_title": self.custom_title,
            "status_message": self.status_message,
            "preferred_color": self.preferred_color,
            "notification_dm": self.notification_dm
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'UserStats':
        """Create from dictionary"""
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif not isinstance(last_updated, datetime):
            last_updated = datetime.now()

        return cls(
            user_id=data["user_id"],
            guild_id=data["guild_id"],
            quests_completed=data.get("quests_completed", 0),
            quests_accepted=data.get("quests_accepted", 0),
            quests_rejected=data.get("quests_rejected", 0),
            last_updated=last_updated,
            points=data.get("points", 0),
            username=data.get("username", ""),
            custom_title=data.get("custom_title", ""),
            status_message=data.get("status_message", ""),
            preferred_color=data.get("preferred_color", "#2C3E50"),
            notification_dm=data.get("notification_dm", True)
        )


@dataclass
class ChannelConfig:
    """Channel configuration data model"""
    guild_id: int
    quest_list_channel: int
    quest_accept_channel: int
    quest_submit_channel: int
    quest_approval_channel: int
    notification_channel: int
    retirement_channel: int
    rank_request_channel: Optional[int] = None
    bounty_channel: Optional[int] = None
    bounty_approval_channel: Optional[int] = None
    mentor_quest_channel: Optional[int] = None
    funeral_channel: Optional[int] = None
    reincarnation_channel: Optional[int] = None
    announcement_channel: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "guild_id": self.guild_id,
            "quest_list_channel": self.quest_list_channel,
            "quest_accept_channel": self.quest_accept_channel,
            "quest_submit_channel": self.quest_submit_channel,
            "quest_approval_channel": self.quest_approval_channel,
            "notification_channel": self.notification_channel,
            "retirement_channel": self.retirement_channel,
            "rank_request_channel": self.rank_request_channel,
            "bounty_channel": self.bounty_channel,
            "bounty_approval_channel": self.bounty_approval_channel,
            "mentor_quest_channel": self.mentor_quest_channel,
            "funeral_channel": self.funeral_channel,
            "reincarnation_channel": self.reincarnation_channel,
            "announcement_channel": self.announcement_channel
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ChannelConfig':
        """Create from dictionary"""
        return cls(
            guild_id=data["guild_id"],
            quest_list_channel=data["quest_list_channel"],
            quest_accept_channel=data["quest_accept_channel"],
            quest_submit_channel=data["quest_submit_channel"],
            quest_approval_channel=data["quest_approval_channel"],
            notification_channel=data["notification_channel"],
            retirement_channel=data["retirement_channel"],
            rank_request_channel=data.get("rank_request_channel"),
            bounty_channel=data.get("bounty_channel"),
            bounty_approval_channel=data.get("bounty_approval_channel"),
            mentor_quest_channel=data.get("mentor_quest_channel"),
            funeral_channel=data.get("funeral_channel"),
            reincarnation_channel=data.get("reincarnation_channel"),
            announcement_channel=data.get("announcement_channel")
        )


@dataclass 
class DepartedMember:
    """Departed member data model for funeral/reincarnation system"""
    member_id: int
    guild_id: int
    username: str
    display_name: str
    avatar_url: Optional[str] = None
    highest_role: Optional[str] = None
    total_points: int = 0
    join_date: Optional[datetime] = None
    leave_date: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    times_left: int = 1
    funeral_message: Optional[str] = None
    had_funeral_role: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "member_id": self.member_id,
            "guild_id": self.guild_id,
            "username": self.username,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "highest_role": self.highest_role,
            "total_points": self.total_points,
            "join_date": self.join_date.isoformat() if self.join_date else None,
            "leave_date": self.leave_date.isoformat() if isinstance(self.leave_date, datetime) else self.leave_date,
            "times_left": self.times_left,
            "funeral_message": self.funeral_message,
            "had_funeral_role": self.had_funeral_role,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DepartedMember':
        """Create from dictionary"""
        join_date = data.get("join_date")
        if isinstance(join_date, str):
            join_date = datetime.fromisoformat(join_date)
            if join_date.tzinfo is not None:
                join_date = join_date.astimezone(timezone.utc).replace(tzinfo=None)
        
        leave_date = data.get("leave_date")
        if isinstance(leave_date, str):
            leave_date = datetime.fromisoformat(leave_date)
            if leave_date.tzinfo is not None:
                leave_date = leave_date.astimezone(timezone.utc).replace(tzinfo=None)
        elif not isinstance(leave_date, datetime):
            leave_date = datetime.now(timezone.utc).replace(tzinfo=None)
            
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
            if created_at.tzinfo is not None:
                created_at = created_at.astimezone(timezone.utc).replace(tzinfo=None)
        elif not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc).replace(tzinfo=None)

        return cls(
            member_id=data["member_id"],
            guild_id=data["guild_id"],
            username=data["username"],
            display_name=data["display_name"],
            avatar_url=data.get("avatar_url"),
            highest_role=data.get("highest_role"),
            total_points=data.get("total_points", 0),
            join_date=join_date,
            leave_date=leave_date,
            times_left=data.get("times_left", 1),
            funeral_message=data.get("funeral_message"),
            had_funeral_role=data.get("had_funeral_role", False),
            created_at=created_at
        )


@dataclass
class MentorQuest:
    """Mentor quest data model"""
    quest_id: str
    title: str
    description: str
    creator_id: int
    disciple_id: int
    guild_id: int
    requirements: str = ""
    reward: str = ""
    rank: str = QuestRank.NORMAL
    category: str = QuestCategory.OTHER
    status: str = QuestStatus.AVAILABLE
    created_at: datetime = field(default_factory=datetime.now)
    required_role_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "quest_id": self.quest_id,
            "title": self.title,
            "description": self.description,
            "creator_id": self.creator_id,
            "disciple_id": self.disciple_id,
            "guild_id": self.guild_id,
            "requirements": self.requirements,
            "reward": self.reward,
            "rank": self.rank,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "required_role_ids": self.required_role_ids
        }


@dataclass
class MentorQuestProgress:
    """Mentor quest progress data model"""
    quest_id: str
    user_id: int
    guild_id: int
    mentor_id: int
    status: str = ProgressStatus.ACCEPTED
    accepted_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    proof_text: str = ""
    proof_image_urls: List[str] = field(default_factory=list)
    channel_id: Optional[int] = None
    rejection_reason: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "quest_id": self.quest_id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "mentor_id": self.mentor_id,
            "status": self.status,
            "accepted_at": self.accepted_at.isoformat() if isinstance(self.accepted_at, datetime) else self.accepted_at,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "proof_text": self.proof_text,
            "proof_image_urls": self.proof_image_urls,
            "channel_id": self.channel_id,
            "rejection_reason": self.rejection_reason
        }


@dataclass
class MentorshipRelationship:
    """Mentorship relationship data model"""
    mentor_id: int
    disciple_id: int
    guild_id: int
    status: str = "active"
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    mentorship_channel_id: Optional[int] = None
    starter_quests_removed: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "mentor_id": self.mentor_id,
            "disciple_id": self.disciple_id,
            "guild_id": self.guild_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if isinstance(self.started_at, datetime) else self.started_at,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "mentorship_channel_id": self.mentorship_channel_id,
            "starter_quests_removed": self.starter_quests_removed
        }


@dataclass  
class LeaderboardEntry:
    """Leaderboard entry data model"""
    guild_id: int
    user_id: int
    username: str
    points: int
    rank: int = 0
    last_updated: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "guild_id": self.guild_id,
            "user_id": self.user_id,
            "username": self.username,
            "points": self.points,
            "rank": self.rank,
            "last_updated": self.last_updated.isoformat() if isinstance(self.last_updated, datetime) else self.last_updated
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LeaderboardEntry':
        """Create from dictionary"""
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif not isinstance(last_updated, datetime):
            last_updated = datetime.now()

        return cls(
            guild_id=data["guild_id"],
            user_id=data["user_id"],
            username=data["username"],
            points=data["points"],
            rank=data.get("rank", 0),
            last_updated=last_updated
        )