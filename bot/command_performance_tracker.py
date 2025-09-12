import time
import logging
from functools import wraps
from typing import Dict, List
import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

def track_command_performance(bot):
    """Decorator to track command performance"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            command_name = func.__name__
            
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                
                # Record performance if monitor is available
                if hasattr(bot, 'performance_monitor'):
                    bot.performance_monitor.record_command_execution(command_name, execution_time)
                
                return result
                
            except Exception as e:
                execution_time = time.time() - start_time
                
                # Record error if monitor is available
                if hasattr(bot, 'performance_monitor'):
                    bot.performance_monitor.record_error()
                
                logger.error(f"❌ Command {command_name} failed after {execution_time:.2f}s: {e}")
                raise
        
        return wrapper
    return decorator

class DatabaseQueryTracker:
    """Track database query performance"""
    
    def __init__(self, database, performance_monitor=None):
        self.database = database
        self.performance_monitor = performance_monitor
        self.query_counts = {}
        self.slow_queries = []
    
    async def execute_tracked_query(self, query: str, *args):
        """Execute a query with performance tracking"""
        start_time = time.time()
        
        try:
            async with self.database.pool.acquire() as conn:
                result = await conn.fetch(query, *args)
                
            execution_time = time.time() - start_time
            
            # Record performance
            if self.performance_monitor:
                self.performance_monitor.record_database_query(execution_time)
            
            # Track slow queries
            if execution_time > 1.0:
                self.slow_queries.append({
                    'query': query[:200] + '...' if len(query) > 200 else query,
                    'execution_time': execution_time,
                    'timestamp': time.time()
                })
                
                # Keep only last 50 slow queries
                if len(self.slow_queries) > 50:
                    self.slow_queries.pop(0)
            
            # Track query counts
            query_type = query.strip().split()[0].upper()
            self.query_counts[query_type] = self.query_counts.get(query_type, 0) + 1
            
            return result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"❌ Database query failed after {execution_time:.2f}s: {e}")
            raise
    
    def get_query_statistics(self) -> Dict:
        """Get query performance statistics"""
        total_queries = sum(self.query_counts.values())
        
        return {
            'total_queries': total_queries,
            'query_breakdown': self.query_counts,
            'slow_query_count': len(self.slow_queries),
            'recent_slow_queries': self.slow_queries[-5:] if self.slow_queries else []
        }