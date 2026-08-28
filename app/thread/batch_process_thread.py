from re import S
from typing import List, Dict, Optional
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from pathlib import Path
import queue
import time
from functools import partial


from app.core.task_factory import TaskFactory
from app.core.entities import (
    TranscribeTask,
    SubtitleTask,
    TranscriptAndSubtitleTask,
    FullProcessTask,
)
from app.thread.transcript_thread import TranscriptThread
from app.thread.subtitle_thread import SubtitleThread
from app.thread.video_synthesis_thread import VideoSynthesisThread
from app.core.utils.logger import setup_logger
from app.core.entities import BatchTaskType, BatchTaskStatus

logger = setup_logger("batch_process_thread")


class BatchTask:
    def __init__(self, file_path: str, task_type: BatchTaskType):
        self.file_path = file_path
        self.task_type = task_type
        self.status = BatchTaskStatus.WAITING
        self.progress = 0
        self.error_message = ""
        self.current_thread: Optional[QThread] = None
        self.cancelled = False


class BatchProcessThread(QThread):
    # 信号定义
    task_progress = pyqtSignal(str, int, str)  # file_path, progress, status
    task_error = pyqtSignal(str, str)  # file_path, error_message
    task_completed = pyqtSignal(str)  # file_path

    def __init__(self):
        super().__init__()
        self.task_queue = queue.Queue()
        self.current_tasks: Dict[str, BatchTask] = {}
        self.max_concurrent_tasks = 1
        self.is_running = False
        self.factory = TaskFactory()
        self.threads = []  # 保存所有创建的线程

    def add_task(self, task: BatchTask):
        self.task_queue.put(task)
        self.current_tasks[task.file_path] = task
        if not self.isRunning():
            self.is_running = True
            self.start()

    def run(self):
        while self.is_running:
            # 检查是否有正在运行的任务数量是否达到上限
            running_tasks = sum(
                1
                for task in self.current_tasks.values()
                if task.status == BatchTaskStatus.RUNNING
            )

            if running_tasks < self.max_concurrent_tasks:
                try:
                    # 非阻塞方式获取任务
                    task = self.task_queue.get_nowait()
                    self._process_task(task)
                except queue.Empty:
                    time.sleep(0.1)  # 避免CPU过度使用
            else:
                time.sleep(0.1)

    def _process_task(self, batch_task: BatchTask):
        try:
            if (
                batch_task.cancelled
                or self.current_tasks.get(batch_task.file_path) is not batch_task
            ):
                return
            batch_task.status = BatchTaskStatus.RUNNING
            self.task_progress.emit(
                batch_task.file_path, 0, str(BatchTaskStatus.RUNNING)
            )

            if batch_task.task_type == BatchTaskType.TRANSCRIBE:
                self._handle_transcribe_task(batch_task)
            elif batch_task.task_type == BatchTaskType.SUBTITLE:
                self._handle_subtitle_task(batch_task)
            elif batch_task.task_type == BatchTaskType.TRANS_SUB:
                self._handle_trans_sub_task(batch_task)
            elif batch_task.task_type == BatchTaskType.FULL_PROCESS:
                self._handle_full_process_task(batch_task)

        except Exception as e:
            logger.exception(f"处理任务失败: {str(e)}")
            batch_task.status = BatchTaskStatus.FAILED
            batch_task.error_message = str(e)
            self.task_error.emit(batch_task.file_path, str(e))

    def _on_progress_wrapper(self, batch_task: BatchTask, progress: int, message: str):
        """进度信号包装器"""
        self.task_progress.emit(batch_task.file_path, progress, message)

    def _on_error_wrapper(self, batch_task: BatchTask, error: str):
        """错误信号包装器"""
        batch_task.status = BatchTaskStatus.FAILED
        batch_task.error_message = error
        self.task_error.emit(batch_task.file_path, error)

    def _on_finished_wrapper(self, batch_task: BatchTask, task=None):
        """完成信号包装器"""
        batch_task.status = BatchTaskStatus.COMPLETED
        batch_task.progress = 100
        self.task_completed.emit(batch_task.file_path)
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)

    def _handle_transcribe_task(self, batch_task: BatchTask):
        # self.max_concurrent_tasks = 3
        task = self.factory.create_transcribe_task(batch_task.file_path)
        thread = TranscriptThread(task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self._on_progress_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self._on_finished_wrapper, batch_task), Qt.QueuedConnection
        )

        thread.start()

    def _handle_subtitle_task(self, batch_task: BatchTask):
        logger.info(f"开始处理字幕任务: {batch_task.file_path}")

        task = self.factory.create_subtitle_task(batch_task.file_path)
        thread = SubtitleThread(task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self._on_progress_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self._on_finished_wrapper, batch_task), Qt.QueuedConnection
        )

        thread.start()

    def _handle_trans_sub_task(self, batch_task: BatchTask):
        task = self.factory.create_transcript_and_subtitle_task(
            batch_task.file_path,
            source_audio_path=(
                getattr(batch_task, "source_audio_path", None)
                or batch_task.file_path
            ),
            article_reference_text=getattr(batch_task, "article_reference_text", ""),
            article_context_data=getattr(batch_task, "article_context_data", None),
            use_article_reference_assist=bool(
                getattr(batch_task, "use_article_reference_assist", False)
            ),
            use_article_translation_terms=bool(
                getattr(batch_task, "use_article_translation_terms", False)
            ),
        )
        trans_task = self.factory.create_transcribe_task(
            batch_task.file_path,
            need_next_task=True,
            source_audio_path=task.source_audio_path,
            article_reference_text=task.article_reference_text,
            article_context_data=task.article_context_data,
            use_article_reference_assist=task.use_article_reference_assist,
            use_article_translation_terms=task.use_article_translation_terms,
        )
        thread = TranscriptThread(trans_task)
        batch_task.current_thread = thread
        self.current_tasks[batch_task.file_path] = batch_task

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self._on_trans_sub_progress_wrapper, batch_task),
            Qt.QueuedConnection,
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self._on_trans_sub_finished_wrapper, batch_task),
            Qt.QueuedConnection,
        )

        thread.start()

    def _on_trans_sub_progress_wrapper(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """转录+字幕任务进度包装器"""
        progress = progress // 2  # 转录占50%进度
        self.task_progress.emit(batch_task.file_path, progress, message)

    def _on_trans_sub_finished_wrapper(
        self, batch_task: BatchTask, task: TranscribeTask
    ):
        """转录+字幕任务转录完成包装器"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)

        # 创建字幕任务
        subtitle_task = self.factory.create_subtitle_task(
            task.output_path,
            batch_task.file_path,
            need_next_task=True,
            source_audio_path=(task.source_audio_path or task.file_path),
            article_reference_text=task.article_reference_text,
            article_context_data=task.article_context_data,
            use_article_reference_assist=task.use_article_reference_assist,
            use_article_translation_terms=task.use_article_translation_terms,
        )
        thread = SubtitleThread(subtitle_task)
        batch_task.current_thread = thread
        self.current_tasks[batch_task.file_path] = batch_task

        # 保存线程引用
        self.threads.append(thread)

        from functools import partial

        thread.progress.connect(
            partial(self._on_trans_sub_subtitle_progress_wrapper, batch_task),
            Qt.QueuedConnection,
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self._on_finished_wrapper, batch_task), Qt.QueuedConnection
        )

        thread.start()

    def _on_trans_sub_subtitle_progress_wrapper(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """转录+字幕任务字幕进度包装器"""
        progress = 50 + progress // 2  # 字幕处理占后50%进度
        self.task_progress.emit(batch_task.file_path, progress, message)

    def _handle_full_process_task(self, batch_task: BatchTask):
        task = self.factory.create_full_process_task(
            batch_task.file_path,
            source_audio_path=(
                getattr(batch_task, "source_audio_path", None)
                or batch_task.file_path
            ),
            article_reference_text=getattr(batch_task, "article_reference_text", ""),
            article_context_data=getattr(batch_task, "article_context_data", None),
            use_article_reference_assist=bool(
                getattr(batch_task, "use_article_reference_assist", False)
            ),
            use_article_translation_terms=bool(
                getattr(batch_task, "use_article_translation_terms", False)
            ),
        )
        # 首先创建转录任务
        trans_task = self.factory.create_transcribe_task(
            batch_task.file_path,
            need_next_task=True,
            source_audio_path=task.source_audio_path,
            article_reference_text=task.article_reference_text,
            article_context_data=task.article_context_data,
            use_article_reference_assist=task.use_article_reference_assist,
            use_article_translation_terms=task.use_article_translation_terms,
        )
        thread = TranscriptThread(trans_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self.on_full_process_progress, batch_task), Qt.QueuedConnection
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self.on_full_process_finished, batch_task), Qt.QueuedConnection
        )

        thread.start()

    def on_full_process_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务的转录进度"""
        if batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = progress // 3  # 转录占33%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def on_full_process_finished(self, batch_task: BatchTask, task: TranscribeTask):
        """处理转录完成后开始字幕任务"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)

        # 转录完成后创建字幕任务
        subtitle_task = self.factory.create_subtitle_task(
            task.output_path,
            batch_task.file_path,
            need_next_task=True,
            source_audio_path=(
                getattr(task, "source_audio_path", None)
                or getattr(task, "file_path", None)
                or batch_task.file_path
            ),
            article_reference_text=getattr(task, "article_reference_text", ""),
            article_context_data=getattr(task, "article_context_data", None),
            use_article_reference_assist=bool(
                getattr(task, "use_article_reference_assist", False)
            ),
            use_article_translation_terms=bool(
                getattr(task, "use_article_translation_terms", False)
            ),
        )
        thread = SubtitleThread(subtitle_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self.on_full_process_subtitle_progress, batch_task),
            Qt.QueuedConnection,
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self.on_full_process_subtitle_finished, batch_task),
            Qt.QueuedConnection,
        )

        thread.start()

    def on_full_process_subtitle_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务中字幕部分的进度"""
        if batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = 33 + progress // 3  # 字幕处理占中间33%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def on_full_process_subtitle_finished(
        self, batch_task: BatchTask, video_path: str, subtitle_path: str
    ):
        """处理字幕完成后开始视频合成任务"""
        if batch_task.current_thread in self.threads:
            self.threads.remove(batch_task.current_thread)

        # 字幕完成后创建视频合成任务
        synthesis_task = self.factory.create_synthesis_task(video_path, subtitle_path)
        thread = VideoSynthesisThread(synthesis_task)
        batch_task.current_thread = thread

        # 保存线程引用
        self.threads.append(thread)

        thread.progress.connect(
            partial(self.on_full_process_synthesis_progress, batch_task),
            Qt.QueuedConnection,
        )
        thread.error.connect(
            partial(self._on_error_wrapper, batch_task), Qt.QueuedConnection
        )
        thread.finished.connect(
            partial(self._on_finished_wrapper, batch_task), Qt.QueuedConnection
        )

        thread.start()

    def on_full_process_synthesis_progress(
        self, batch_task: BatchTask, progress: int, message: str
    ):
        """处理全流程任务中视频合成部分的进度"""
        if batch_task.status == BatchTaskStatus.RUNNING:
            progress_value = 66 + progress // 3  # 视频合成占最后34%进度
            self.task_progress.emit(batch_task.file_path, progress_value, message)

    def stop_task(self, file_path: str):
        task = self.current_tasks.pop(file_path, None)
        if task is not None:
            task.cancelled = True
            if task.current_thread:
                if hasattr(task.current_thread, "stop"):
                    task.current_thread.stop()
        # Remove only the requested queued task. Other files must keep running.
        with self.task_queue.mutex:
            queued = list(self.task_queue.queue)
            remaining = [item for item in queued if item.file_path != file_path]
            removed_count = len(queued) - len(remaining)
            self.task_queue.queue.clear()
            self.task_queue.queue.extend(remaining)
            if removed_count:
                self.task_queue.unfinished_tasks = max(
                    0, self.task_queue.unfinished_tasks - removed_count
                )
                if self.task_queue.unfinished_tasks == 0:
                    self.task_queue.all_tasks_done.notify_all()

    def stop_all(self):
        self.is_running = False
        # 停止所有线程
        for thread in self.threads:
            if hasattr(thread, "stop"):
                thread.stop()
            thread.wait()  # 等待线程结束
        self.threads.clear()
        self.current_tasks.clear()
        # 清空任务队列
        with self.task_queue.mutex:
            self.task_queue.queue.clear()
