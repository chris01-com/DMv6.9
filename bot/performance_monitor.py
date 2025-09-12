import asyncio
import psutil
import time
import logging
from typing import Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Real-time performance monitoring for the Discord bot"""
    
    def __init__(self, bot):
        self.bot = bot
        self.metrics = {
            'commands_executed': 0,
            'database_queries': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'memory_usage': [],
            'cpu_usage': [],
            'response_times': [],
            'active_views': 0,
            'error_count': 0
        }
        self.start_time = datetime.now()
        self.monitoring_task = None
    
    def start_monitoring(self):
        """Start the performance monitoring task"""
        self.monitoring_task = asyncio.create_task(self._monitor_loop())
        logger.info("🔍 Performance monitoring started")
    
    def stop_monitoring(self):
        """Stop the performance monitoring task"""
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
        logger.info("🔍 Performance monitoring stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while True:
            try:
                # Collect system metrics
                memory_percent = psutil.virtual_memory().percent
                cpu_percent = psutil.cpu_percent()
                
                # Store metrics (keep last 100 readings)
                self.metrics['memory_usage'].append(memory_percent)
                self.metrics['cpu_usage'].append(cpu_percent)
                
                if len(self.metrics['memory_usage']) > 100:
                    self.metrics['memory_usage'].pop(0)
                if len(self.metrics['cpu_usage']) > 100:
                    self.metrics['cpu_usage'].pop(0)
                
                # Log alerts for high usage
                if memory_percent > 85:
                    logger.warning(f"⚠️ High memory usage: {memory_percent:.1f}%")
                if cpu_percent > 80:
                    logger.warning(f"⚠️ High CPU usage: {cpu_percent:.1f}%")
                
                # Clean up old response times (keep last 1000)
                if len(self.metrics['response_times']) > 1000:
                    self.metrics['response_times'] = self.metrics['response_times'][-1000:]
                
                # Monitor active views count
                if hasattr(self.bot, 'commands') and hasattr(self.bot.commands, 'active_leaderboard_views'):
                    self.metrics['active_views'] = len(self.bot.commands.active_leaderboard_views)
                
                await asyncio.sleep(30)  # Monitor every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Error in performance monitoring: {e}")
                await asyncio.sleep(30)
    
    def record_command_execution(self, command_name: str, execution_time: float):
        """Record command execution metrics"""
        self.metrics['commands_executed'] += 1
        self.metrics['response_times'].append(execution_time)
        
        if execution_time > 5.0:  # Log slow commands
            logger.warning(f"⚠️ Slow command execution: {command_name} took {execution_time:.2f}s")
    
    def record_database_query(self, execution_time: float):
        """Record database query metrics"""
        self.metrics['database_queries'] += 1
        
        if execution_time > 2.0:  # Log slow queries
            logger.warning(f"⚠️ Slow database query: {execution_time:.2f}s")
    
    def record_cache_hit(self):
        """Record cache hit"""
        self.metrics['cache_hits'] += 1
    
    def record_cache_miss(self):
        """Record cache miss"""
        self.metrics['cache_misses'] += 1
    
    def record_error(self):
        """Record error occurrence"""
        self.metrics['error_count'] += 1
    
    def get_performance_report(self) -> Dict:
        """Generate comprehensive performance report"""
        uptime = datetime.now() - self.start_time
        
        # Calculate averages
        avg_memory = sum(self.metrics['memory_usage'][-10:]) / len(self.metrics['memory_usage'][-10:]) if self.metrics['memory_usage'] else 0
        avg_cpu = sum(self.metrics['cpu_usage'][-10:]) / len(self.metrics['cpu_usage'][-10:]) if self.metrics['cpu_usage'] else 0
        avg_response_time = sum(self.metrics['response_times'][-100:]) / len(self.metrics['response_times'][-100:]) if self.metrics['response_times'] else 0
        
        # Calculate cache hit rate
        total_cache_operations = self.metrics['cache_hits'] + self.metrics['cache_misses']
        cache_hit_rate = (self.metrics['cache_hits'] / total_cache_operations * 100) if total_cache_operations > 0 else 0
        
        return {
            'uptime': str(uptime),
            'commands_executed': self.metrics['commands_executed'],
            'database_queries': self.metrics['database_queries'],
            'avg_memory_usage': f"{avg_memory:.1f}%",
            'avg_cpu_usage': f"{avg_cpu:.1f}%",
            'avg_response_time': f"{avg_response_time:.2f}s",
            'cache_hit_rate': f"{cache_hit_rate:.1f}%",
            'active_views': self.metrics['active_views'],
            'error_count': self.metrics['error_count'],
            'commands_per_minute': self.metrics['commands_executed'] / (uptime.total_seconds() / 60) if uptime.total_seconds() > 0 else 0
        }