from typing import Optional
from bot.sql_database import SQLDatabase
from bot.models import ChannelConfig as ChannelConfigModel


class ChannelConfig:
    """Manages channel configuration for guilds"""
    
    def __init__(self, database: SQLDatabase):
        self.database = database
    
    async def initialize(self):
        """Initialize the channel config manager"""
        # No special initialization needed for SQL version
        pass
    
    async def set_guild_channels(self, guild_id: int, quest_list_channel: int,
                               quest_accept_channel: int, quest_submit_channel: int,
                               quest_approval_channel: int, notification_channel: int,
                               retirement_channel: int, rank_request_channel: Optional[int] = None, 
                               bounty_channel: Optional[int] = None, bounty_approval_channel: Optional[int] = None,
                               mentor_quest_channel: Optional[int] = None,
                               funeral_channel: Optional[int] = None, reincarnation_channel: Optional[int] = None,
                               announcement_channel: Optional[int] = None):
        """Set channel configuration for a guild"""
        config = ChannelConfigModel(
            guild_id=guild_id,
            quest_list_channel=quest_list_channel,
            quest_accept_channel=quest_accept_channel,
            quest_submit_channel=quest_submit_channel,
            quest_approval_channel=quest_approval_channel,
            notification_channel=notification_channel,
            retirement_channel=retirement_channel,
            rank_request_channel=rank_request_channel,
            bounty_channel=bounty_channel,
            bounty_approval_channel=bounty_approval_channel,
            mentor_quest_channel=mentor_quest_channel,
            funeral_channel=funeral_channel,
            reincarnation_channel=reincarnation_channel,
            announcement_channel=announcement_channel
        )
        await self.database.save_channel_config(config)
    
    async def get_guild_config(self, guild_id: int) -> Optional[ChannelConfigModel]:
        """Get channel configuration for a guild"""
        return await self.database.get_channel_config(guild_id)
    
    async def get_quest_list_channel(self, guild_id: int) -> Optional[int]:
        """Get quest list channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.quest_list_channel if config else None
    
    async def get_quest_accept_channel(self, guild_id: int) -> Optional[int]:
        """Get quest accept channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.quest_accept_channel if config else None
    
    async def get_quest_submit_channel(self, guild_id: int) -> Optional[int]:
        """Get quest submit channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.quest_submit_channel if config else None
    
    async def get_quest_approval_channel(self, guild_id: int) -> Optional[int]:
        """Get quest approval channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.quest_approval_channel if config else None
    
    async def get_notification_channel(self, guild_id: int) -> Optional[int]:
        """Get notification channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.notification_channel if config else None
    
    async def get_retirement_channel(self, guild_id: int) -> Optional[int]:
        """Get retirement channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.retirement_channel if config else None
    
    async def get_rank_request_channel(self, guild_id: int) -> Optional[int]:
        """Get rank request channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.rank_request_channel if config else None
    
    async def get_bounty_channel(self, guild_id: int) -> Optional[int]:
        """Get bounty channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.bounty_channel if config else None
    
    async def get_bounty_approval_channel(self, guild_id: int) -> Optional[int]:
        """Get bounty approval channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.bounty_approval_channel if config else None
    
    async def get_funeral_channel(self, guild_id: int) -> Optional[int]:
        """Get funeral channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.funeral_channel if config else None
    
    async def get_reincarnation_channel(self, guild_id: int) -> Optional[int]:
        """Get reincarnation channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.reincarnation_channel if config else None
    
    async def get_mentor_quest_channel(self, guild_id: int) -> Optional[int]:
        """Get mentor quest channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.mentor_quest_channel if config else None
    
    async def get_announcement_channel(self, guild_id: int) -> Optional[int]:
        """Get announcement channel for a guild"""
        config = await self.get_guild_config(guild_id)
        return config.announcement_channel if config else None