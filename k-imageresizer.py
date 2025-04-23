import os
from subprocess import Popen
import threading
import wx
import wx.adv
import json
from PIL import Image as PILImage, ImageOps, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
import shutil
import wx.richtext as rt
import time
import re
import psutil
from wx.lib.agw.floatspin import FloatSpin


# 설정을 저장할 JSON 파일 경로
SETTINGS_FILE = "settings.json"

# 기본 설정 값
DEFAULT_SETTINGS = {
    "max_width": 1024,
    "max_size_kb": 300,
    "min_quality": 85,
    "output_format": "JPEG",
    "clear_folder": True,
    "mode": 1,
}


def clear_folder(folder_path):
    """지정한 폴더 내의 파일을 모두 삭제합니다."""
    if not os.path.isdir(folder_path):
        print("폴더가 존재하지 않습니다.")
        return

    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                e_ = f"{e}".replace("\\\\", "\\")
                print(f"❌ 파일 삭제 실패: {file_path} - {e_}")
                wx.MessageBox(f"❌ 파일 삭제 실패: {os.path.basename(file_path)}", "오류", wx.ICON_ERROR)

def normalize_extension(output_path, format_name):
    if format_name.lower() in ["jpeg", "jpg"]:
        base, _ = os.path.splitext(output_path)
        return base + ".jpg"
    return output_path

def show_image_viewer_with_splash(parent, images):
    viewer = ImageViewerFrame(parent, "이미지 뷰어", images)

class Toast(wx.Frame):
    def __init__(self, parent, message, duration=1500):
        style = wx.STAY_ON_TOP | wx.FRAME_NO_TASKBAR | wx.NO_BORDER
        super().__init__(parent, style=style)

        panel = wx.Panel(self)
        text = wx.StaticText(panel, label=message)
        font = text.GetFont()
        font.MakeBold()
        text.SetFont(font)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(text, 0, wx.ALL | wx.ALIGN_CENTER, 10)
        panel.SetSizer(sizer)
        sizer.Fit(self)

        self.SetBackgroundColour("#444")
        panel.SetBackgroundColour("#444")
        text.SetForegroundColour("white")

        self.CenterOnScreen()
        self.Show()

        # 자동 닫기
        wx.CallLater(duration, self.Close)


class ImageViewerFrame(wx.Frame):
    def __init__(self, parent, title, images, start_index=0, on_delete_callback=None, on_restore_callback=None, splash=None):
        super().__init__(parent, title=title, size=(948, 600))

        self.parent = parent
        self.images = images
        self.start_index = start_index
        self.on_delete_callback = on_delete_callback  # 부모 쪽의 콜백 저장
        self.on_restore_callback = on_restore_callback  # 부모 쪽의 콜백 저장

        self.current_image_idx = start_index
        self.thumbnail_size = (80, 80)
        self.delete_stack = []  # 🔁 최근 삭제 항목들을 쌓아둘 스택

        self.panel = wx.Panel(self)
        self.vbox = wx.BoxSizer(wx.VERTICAL)

        # 메인 이미지 표시용
        self.image_bitmap = wx.StaticBitmap(self.panel)
        self.vbox.Add(self.image_bitmap, 1, wx.EXPAND | wx.ALL, 5)

        self.resolution_text = wx.StaticText(self.panel, label="", style=wx.ALIGN_CENTER)
        self.resolution_text.SetForegroundColour(wx.Colour(255, 255, 255))  # 흰 글씨
        self.resolution_text.SetBackgroundColour(wx.Colour(0, 0, 0))  # 검은 배경
        font = self.resolution_text.GetFont()
        font.MakeBold()
        self.resolution_text.SetFont(font)

        self.vbox.Add(self.resolution_text, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.BOTTOM, 10)

        # 내비게이션 바
        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # 도움말
        self.help_center_btn = wx.Button(self.panel, label="도움말 📘")
        self.help_center_btn.Bind(wx.EVT_BUTTON, self.open_help_center)
        nav_sizer.Add(self.help_center_btn, 0, wx.RIGHT, 10)

        # 삭제 취소 버튼
        self.undo_btn = wx.Button(self.panel, label="⎌ 삭제 취소")
        self.undo_btn.Bind(wx.EVT_BUTTON, self.on_undo_delete)
        nav_sizer.Add(self.undo_btn, 0, wx.RIGHT, 10)

        # ◀◀ 맨처음 버튼
        self.first_btn = wx.Button(self.panel, label="⏮ 처음")
        self.first_btn.Bind(wx.EVT_BUTTON, lambda evt: self.show_first_image())
        nav_sizer.Add(self.first_btn, 0, wx.RIGHT, 10)

        # ◀ 이전 버튼
        self.prev_btn = wx.Button(self.panel, label="◀ 이전")
        self.prev_btn.Bind(wx.EVT_BUTTON, lambda evt: self.show_previous_image())
        nav_sizer.Add(self.prev_btn, 0, wx.RIGHT, 10)

        # 페이지 표시
        #nav_sizer.AddSpacer(100)
        self.page_label = wx.StaticText(self.panel, label="1 / 1")
        nav_sizer.Add(self.page_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)

        # 다음 ▶ 버튼
        self.next_btn = wx.Button(self.panel, label="다음 ▶")
        self.next_btn.Bind(wx.EVT_BUTTON, lambda evt: self.show_next_image())
        nav_sizer.Add(self.next_btn, 0, wx.RIGHT, 10)

        # ▶▶ 맨끝 버튼
        self.last_btn = wx.Button(self.panel, label="끝 ⏭")
        self.last_btn.Bind(wx.EVT_BUTTON, lambda evt: self.show_last_image())
        nav_sizer.Add(self.last_btn, 0, wx.RIGHT, 10)

        # 리스트에서 삭제 버튼
        self.delete_btn = wx.Button(self.panel, label="🗑 리스트에서 삭제")
        self.delete_btn.Bind(wx.EVT_BUTTON, self.on_delete_image)
        nav_sizer.Add(self.delete_btn, 0)

        self.vbox.Add(nav_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        # 썸네일 내비게이션 바
        self.thumb_panel = wx.ScrolledWindow(self.panel, style=wx.HSCROLL)
        self.thumb_panel.SetScrollRate(5, 0)
        self.thumb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.thumb_panel.SetSizer(self.thumb_sizer)
        self.vbox.Add(self.thumb_panel, 0, wx.EXPAND | wx.ALL, 5)

        self.panel.SetSizer(self.vbox)

        self.Center()
        self.Show()

        self.thumbnails = []
        self.load_thumbnails()
        self.update_scroll_rate()

        # 더블 클릭 시 이미지뷰어를 닫는 이벤트 바인딩
        self.image_bitmap.Bind(wx.EVT_LEFT_DCLICK, self.on_double_click)

        # 화살표 키로 내비게이션
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_NORMAL, wx.WXK_LEFT, wx.ID_BACKWARD), # 왼쪽 화살표 키
            (wx.ACCEL_NORMAL, wx.WXK_RIGHT, wx.ID_FORWARD), # 오른쪽 화살표 키
            (wx.ACCEL_NORMAL, wx.WXK_ESCAPE, wx.ID_CANCEL), # Esc 키
            (wx.ACCEL_NORMAL, wx.WXK_DELETE, wx.ID_DELETE),  # Delete 키
            (wx.ACCEL_CTRL, ord('Z'), wx.ID_UNDO),  # Ctrl+Z
            (wx.ACCEL_NORMAL, wx.WXK_F1, wx.ID_HELP) , # F1 키
            (wx.ACCEL_NORMAL, ord('H'), wx.ID_HELP)  # 🆕 H 키 등록
        ])
        self.SetAcceleratorTable(accel_tbl)

        self.Bind(wx.EVT_MENU, lambda e: self.Close(), id=wx.ID_CANCEL)
        self.Bind(wx.EVT_MENU, lambda e: self.show_previous_image(), id=wx.ID_BACKWARD)
        self.Bind(wx.EVT_MENU, lambda e: self.show_next_image(), id=wx.ID_FORWARD)
        self.Bind(wx.EVT_MENU, lambda e: self.on_delete_image(e), id=wx.ID_DELETE)
        self.Bind(wx.EVT_MENU, lambda e: self.on_undo_delete(e), id=wx.ID_UNDO)
        self.Bind(wx.EVT_MENU, lambda e: self.open_help_center(e), id=wx.ID_HELP)

        self.Bind(wx.EVT_CLOSE, self.OnClose)

        self.load_image()
        if splash:
            wx.CallAfter(lambda: splash.Destroy() ) # 모두 로드한 뒤 스플래시 제거


    def open_help_center(self, event):
        dlg = HelpCenterDialog(self)
        dlg.ShowModal()

    def on_delete_image(self, event):
        if len(self.thumbnails) == 1:
            wx.MessageBox("하나밖에 없는 썸네일! 삭제하지 말아 주세요.", "알림", wx.ICON_INFORMATION)
            return

        path = self.images[self.current_image_idx]
        """
        confirm = wx.MessageBox(f"리스트에서 해당 이미지를 삭제할까요?\n\n{path}",
                                "리스트에서 삭제",
                                wx.ICON_QUESTION | wx.YES_NO)
        if confirm != wx.YES:
            return
        """
        # 삭제 직전 정보 저장
        self.delete_stack.append((path, self.current_image_idx))

        # 🔥 썸네일 삭제
        thumb_to_remove = self.thumbnails.pop(self.current_image_idx)
        thumb_to_remove.Destroy()  # UI에서 삭제
        del thumb_to_remove  # 참조도 제거

        # 🔥 이미지 목록에서도 삭제
        del self.images[self.current_image_idx]

        # 🔥 썸네일 레이아웃 갱신
        self.thumb_panel.Layout()
        self.thumb_panel.FitInside()
        self.update_scroll_rate()

        # 🔥 호출자에게 알려서 리스트컨트롤에서 해당 항목 삭제하게 함
        if self.on_delete_callback:
            self.on_delete_callback(path)

        # 🔄 뷰어 이미지 전환 or 닫기
        if not self.images:
            self.Close()
        else:
            if self.current_image_idx >= len(self.images):
                self.current_image_idx -= 1
            self.load_image()

        # 썸네일 삭제 후 인덱스 바인딩 갱신
        self.rebind_thumbnail_events()
        Toast(self, f"리스트에서 삭제됨: {os.path.basename(path)}", 1000)

    def on_undo_delete(self, event):
        if not self.delete_stack:
            wx.MessageBox("되살릴 항목이 없습니다.", "알림", wx.ICON_INFORMATION)
            return

        path, index = self.delete_stack.pop()
        self.images.insert(index, path)

        # 썸네일 복원
        try:
            img = PILImage.open(path)
            img = ImageOps.exif_transpose(img)
            img.thumbnail(self.thumbnail_size)

            wx_img = wx.Image(img.size[0], img.size[1])
            wx_img.SetData(img.convert("RGB").tobytes())
            bmp = wx.Bitmap(wx_img)

            thumb_panel = wx.Panel(self.thumb_panel, size=(self.thumbnail_size[0] + 8, self.thumbnail_size[1] + 8))
            thumb_panel.SetBackgroundColour(wx.NullColour)

            thumb_bitmap = wx.StaticBitmap(thumb_panel, bitmap=bmp)
            thumb_bitmap.Center()
            thumb_bitmap.Bind(wx.EVT_LEFT_DOWN, lambda evt, i=index: self.on_thumbnail_click(i))

            self.thumbnails.insert(index, thumb_panel)
            self.thumb_sizer.Insert(index + 1, thumb_panel, 0, wx.ALL, 2)  # +1 to skip left spacer

        except Exception as e:
            e_ = f"{e}".replace("\\\\", "\\")
            print(f"❌ 썸네일 복원 실패: {path} - {e_}")
            wx.MessageBox(f"❌ 썸네일 복원 실패: {os.path.basename(path)}", "오류", wx.ICON_ERROR)

        self.rebind_thumbnail_events()
        self.thumb_panel.Layout()
        self.thumb_panel.FitInside()
        self.update_scroll_rate()

        self.load_image()

        # 🔁 호출자에게 복원 알림
        if self.on_restore_callback:
            self.on_restore_callback(path, index)

        Toast(self, f"리스트에 복원: {os.path.basename(path)}", 1000)

    def rebind_thumbnail_events(self):
        for idx, thumb_panel in enumerate(self.thumbnails):
            children = thumb_panel.GetChildren()
            if not children:
                continue

            thumb_bitmap = children[0]

            # 기존 핸들러 해제 (바로 이벤트 언바인드)
            thumb_bitmap.Unbind(wx.EVT_LEFT_DOWN)

            # 새 인덱스로 이벤트 다시 바인딩
            thumb_bitmap.Bind(wx.EVT_LEFT_DOWN, lambda evt, i=idx: self.on_thumbnail_click(i))

    def update_scroll_rate(self):
        """썸네일 수, 해상도, 화면 크기에 따라 적절한 스크롤 단위를 설정"""
        thumb_count = len(self.thumbnails)
        panel_width = self.thumb_panel.GetClientSize().width

        # 기준 썸네일 크기 + 마진 포함
        thumb_width = self.thumbnail_size[0] + 8 + 4  # padding 고려

        # 전체 썸네일이 패널보다 작으면 스크롤 안 해도 됨
        total_thumb_width = thumb_count * thumb_width
        if total_thumb_width <= panel_width:
            self.thumb_panel.SetScrollRate(0, 0)
            return

        # 총 썸네일 너비 대비 스크롤 폭을 적절히 조정
        scroll_unit = max(1, min(thumb_width // 4, 10))  # 1~10 사이 적절히 조절
        self.thumb_panel.SetScrollRate(scroll_unit, 0)

    def on_double_click(self, event):
        self.Close()  # 더블클릭 시 이미지뷰어를 닫음

    def load_thumbnails(self):
        for idx, path in enumerate(self.images):
            try:
                img = PILImage.open(path)
                img = ImageOps.exif_transpose(img)
                img.thumbnail(self.thumbnail_size)

                wx_img = wx.Image(img.size[0], img.size[1])
                wx_img.SetData(img.convert("RGB").tobytes())
                bmp = wx.Bitmap(wx_img)

                thumb_panel = wx.Panel(self.thumb_panel, size=(self.thumbnail_size[0]+8, self.thumbnail_size[1]+8))
                thumb_panel.SetBackgroundColour(wx.NullColour)

                thumb_bitmap = wx.StaticBitmap(thumb_panel, bitmap=bmp)
                thumb_bitmap.Center()
                thumb_bitmap.Bind(wx.EVT_LEFT_DOWN, lambda evt, i=idx: self.on_thumbnail_click(i))

                self.thumb_sizer.Add(thumb_panel, 0, wx.ALL, 2)
                self.thumbnails.append(thumb_panel)

            except Exception as e:
                e_ = f"{e}".replace("\\\\", "\\")
                print(f"❌ 썸네일 생성 실패: {path} - {e_}")
                wx.MessageBox(f"❌ 썸네일 생성 실패: {os.path.basename(path)}", "오류", wx.ICON_ERROR)


        self.thumb_sizer.AddStretchSpacer(1)
        self.thumb_panel.Layout()
        self.thumb_panel.FitInside()
        self.thumb_panel.SetVirtualSize(self.thumb_sizer.GetMinSize())
        self.panel.Layout()

    def on_thumbnail_click(self, idx):
        if idx == self.current_image_idx:
            return

        self.current_image_idx = idx
        self.load_image()
        self.highlight_thumbnail(idx)

    def load_image(self):
        path = self.images[self.current_image_idx]

        try:
            with PILImage.open(path) as img:
                img = ImageOps.exif_transpose(img)

                panel_width, panel_height = self.panel.GetSize()
                panel_height -= self.thumbnail_size[1] + 80

                # ⭐ 원본 해상도
                original_width, original_height = img.size

                # ⭐ 파일 용량
                file_size_bytes = os.path.getsize(path)

                # 용량 포맷: 1MB 이상이면 MB, 그 외에는 KB로 표시
                if file_size_bytes >= 1024 * 1024:
                    file_size = f"{file_size_bytes / (1024 * 1024):.1f} MB"
                else:
                    file_size = f"{file_size_bytes / 1024:.1f} KB"

                # 이미지 포맷
                file_format = img.format or os.path.splitext(path)[1][1:].upper().replace('JPG', 'JPEG').replace('WEBP', 'WebP')  # JPG, PNG 등

                # 해상도 + 용량 + 포맷 정보 결합
                size_label = f"  {original_width}×{original_height}  |  {file_size}  |  {file_format}  "

                # 리사이즈 처리
                panel_width, panel_height = self.panel.GetSize()
                panel_height -= self.thumbnail_size[1] + 50

                scale = min(panel_width / original_width, panel_height / original_height, 1.0)
                img = img.resize((int(original_width * scale), int(original_height * scale)), PILImage.LANCZOS)

                wx_img = wx.Image(img.size[0], img.size[1])
                wx_img.SetData(img.convert("RGB").tobytes())
                bitmap = wx_img.ConvertToBitmap()

                old_bitmap = self.image_bitmap.GetBitmap()
                if old_bitmap.IsOk():
                    old_bitmap.Destroy()  # 수동 제거 (옵션)

                self.image_bitmap.SetBitmap(bitmap)
                self.page_label.SetLabel(f"{self.current_image_idx + 1} / {len(self.images)}")

                # 해상도 표시 갱신
                self.resolution_text.SetLabel(size_label)

                self.prev_btn.Enable(self.current_image_idx > 0)
                self.next_btn.Enable(self.current_image_idx < len(self.images) - 1)

                self.highlight_thumbnail(self.current_image_idx)
                self.panel.Layout()

        except Exception as e:
            e_ = f"{e}".replace("\\\\", "\\")
            print(f"❌ 이미지 로드 실패: {path} - {e_}")
            wx.MessageBox(f"❌ 이미지 로드 실패: {os.path.basename(path)}", "오류", wx.ICON_ERROR)

    def show_first_image(self):
        self.current_image_idx = 0
        self.load_image()

    def show_last_image(self):
        self.current_image_idx = len(self.images) - 1
        self.load_image()

    def show_previous_image(self):
        if self.current_image_idx > 0:
            self.current_image_idx -= 1
            self.load_image()

    def show_next_image(self):
        if self.current_image_idx < len(self.images) - 1:
            self.current_image_idx += 1
            self.load_image()

    def highlight_thumbnail(self, idx):
        for i, thumb in enumerate(self.thumbnails):
            if i == idx:
                thumb.SetBackgroundColour(wx.Colour(30, 144, 255))  # DodgerBlue
            else:
                thumb.SetBackgroundColour(wx.NullColour)
            thumb.Refresh()

        # 자동 스크롤 조건 검사 및 실행
        if not self.is_thumbnail_fully_visible(idx):
            self.scroll_thumbnail_to_center(idx)

    def scroll_thumbnail_to_center(self, idx):
        if 0 <= idx < len(self.thumbnails):
            self.thumb_panel.Layout()
            wx.Yield()  # 레이아웃 보정

            thumb = self.thumbnails[idx]
            thumb_width = thumb.GetSize().width

            # 좌표 계산
            thumb_screen_pos = thumb.ClientToScreen((0, 0))
            thumb_left = thumb_screen_pos[0] + thumb_width // 2  # 중심 좌표

            panel_screen_pos = self.thumb_panel.ClientToScreen((0, 0))
            panel_left = panel_screen_pos[0]
            panel_width = self.thumb_panel.GetClientSize().width
            panel_center = panel_left + panel_width // 2

            scroll_rate_x, _ = self.thumb_panel.GetScrollPixelsPerUnit()

            # 썸네일 중심과 패널 중심 간 차이 계산
            delta_px = thumb_left - panel_center
            current_scroll_px = self.thumb_panel.GetViewStart()[0] * scroll_rate_x
            target_scroll_px = max(0, current_scroll_px + delta_px)
            scroll_units = target_scroll_px // scroll_rate_x

            self.thumb_panel.Scroll(scroll_units, 0)

    def is_thumbnail_fully_visible(self, idx):
        if 0 <= idx < len(self.thumbnails):
            self.thumb_panel.Layout()  # 레이아웃 갱신 보장
            wx.Yield()  # GUI 이벤트 강제 반영

            thumb = self.thumbnails[idx]
            thumb_pos = thumb.ClientToScreen((0, 0))
            thumb_width = thumb.GetSize().width
            thumb_left = thumb_pos[0]
            thumb_right = thumb_left + thumb_width

            panel_pos = self.thumb_panel.ClientToScreen((0, 0))
            panel_width = self.thumb_panel.GetClientSize().width
            panel_left = panel_pos[0]
            panel_right = panel_left + panel_width

            # 디버그 로그
            # print(f"[검사중] 썸네일 {idx} - left:{thumb_left}, right:{thumb_right}")
            # print(f"[뷰포트] panel - left:{panel_left}, right:{panel_right}")

            # 오차 허용 범위 (픽셀)
            tolerance = 1

            # 썸네일이 완전히 뷰포트 안에 들어 있는지 확인
            return (
                    thumb_left >= panel_left - tolerance and
                    thumb_right <= panel_right + tolerance
            )
        return False

    def OnClose(self, event=None):
        self.parent.input_listctrl.Select(self.start_index, on=False)
        self.parent.input_listctrl.Select(self.current_image_idx)
        for thumb in self.thumbnails:
            thumb.Destroy()
        self.thumbnails.clear()
        self.image_bitmap.SetBitmap(wx.NullBitmap)  # 메모리 해제
        self.Destroy()


class FileDropHandler(wx.FileDropTarget):
    def __init__(self, listbox, callback):
        super().__init__()
        self.listbox = listbox
        self.callback = callback  # 드롭 후 수행할 함수

    def OnDropFiles(self, x, y, filenames):
        self.callback(filenames)
        return True


class HelpCenterDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="도움말", size=(620, 600))

        panel = wx.Panel(self)

        notebook = wx.Notebook(panel)

        # 각 탭에 RichTextCtrl 추가
        self.add_help_tab(notebook, " 출력 옵션 ", self.get_output_help())
        self.add_help_tab(notebook, " 출력 경로 ", self.get_output_path_help())
        self.add_help_tab(notebook, " 입력 경로 ", self.get_input_help())
        self.add_help_tab(notebook, " 입력경로 리스트 사용법 ", self.get_listctrl_help())
        self.add_help_tab(notebook, " 이미지 뷰어 사용법 ", self.get_image_viewer_help())
        if parent.__class__.__name__ == 'ImageViewerFrame':
            notebook.SetSelection(4)

        close_btn = wx.Button(panel, wx.ID_OK, "닫기")

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)

        panel.SetSizer(sizer)
        self.Centre()
        self.ShowModal()
        self.Destroy()

    def add_help_tab(self, notebook, title, text):
        page = wx.Panel(notebook)
        help_text = rt.RichTextCtrl(page, style=wx.TE_MULTILINE | wx.BORDER_NONE | wx.TE_READONLY)
        help_text.SetFont(wx.Font(9, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL))
        help_text.SetMargins(10, 10)  # 여백

        # 🔹 줄간격 스타일 적용
        attr = rt.RichTextAttr()
        attr.SetLineSpacing(15)  # 줄 간격 설정
        help_text.SetDefaultStyle(attr)
        help_text.BeginStyle(attr)
        help_text.WriteText(text)
        help_text.EndStyle()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(help_text, 1, wx.EXPAND)
        page.SetSizer(sizer)
        notebook.AddPage(page, title)

    def get_output_help(self):
        return (
            "📤 출력 옵션 도움말\n\n"
            "🔹 너비 (px)\n"
            "이미지를 지정한 너비로 축소합니다. 가로/세로 비율을 유지하며 리사이징됩니다.\n\n"
            "🔹 용량 (KB)\n"
            "이미지를 설정된 크기 이하로 압축합니다. 값이 낮을수록 이미지의 화질은 떨어질 수 있습니다.\n\n"
            "🔹 화질 (1~100)\n"
            "JPEG 또는 WebP 형식으로 이미지를 압축할 경우의 화질 수준을 의미합니다. 값이 낮을수록 파일 용량은 작아지지만, 이미지의 화질은 떨어질 수 있습니다.\n\n"
            "- 이미지 가로 폭 기준 적정 JPEG 품질 (Full HD 모니터 기준)\n"
            "≤ 800px		70	(썸네일, 미리보기, 리스트 이미지)\n"
            "801 ~ 1280px		75	(블로그 본문 이미지, 일반 웹 콘텐츠)\n"
            "1281 ~ 1920px	85	(웹 배경 이미지, 상세 콘텐츠)\n"
            "1921 ~ 2560px	90	(QHD 콘텐츠, 확대 가능한 이미지)\n"
            "> 2560px		95	(고해상도 포트폴리오, 사진 원본, 인쇄 전용)\n\n"
            "- 이미지 가로 폭 기준 적정 WebP 품질 (Full HD 모니터 기준)\n"
            "≤ 800px		60	(썸네일, 미리보기, 리스트 이미지)\n"
            "801 ~ 1280px		70	(블로그 본문 이미지, 일반 웹 콘텐츠)\n"
            "1281 ~ 1920px	80	(웹 배경 이미지, 상세 콘텐츠)\n"
            "1921 ~ 2560px	90	(QHD 콘텐츠, 확대 가능한 이미지)\n"
            "> 2560px		95	(고해상도 포트폴리오, 사진 원본, 인쇄 전용)\n\n"
            "📝 텍스트 포함 이미지는 손실이 더 도드라지므로 85 이상을 권장합니다(JPEG, WebP 공통). PNG 형식(무손실 압축!)으로 출력하는 것도 한 방법일 수 있습니다.\n\n"
            "🔹 출력 형식\n"
            "- JPEG: 일반 사진용, 고효율 압축\n"
            "- PNG: 투명도 지원, 무손실 압축\n"
            "- WebP: 고압축 + 투명도 지원 (권장)\n"
            "- TIFF, BMP 등은 일부 환경에서 제한됨.\n\n"
            "💡 원본의 너비가 최대 너비보다 작고 용량 또한 최대 용량보다 작으면 리사이징/압축 없이 원본 그대로 저장됩니다.\n"
        )

    def get_output_path_help(self):
        return (
            "📂 출력 경로 도움말\n\n"
            "🔹 경로 지정\n"
            "변환된 이미지들이 저장될 폴더를 지정합니다. '폴더 선택' 버튼을 클릭해 선택할 수 있습니다.\n\n"
            "🔹 저장 폴더의 자동 지정\n"
            "입력 경로의 첫 번째 이미지가 있는 폴더 아래의 '출력' 폴더로 지정됩니다. 물론, '폴더 선택' 버튼을 클릭해 다른 폴더로 변경할 수 있습니다.\n\n"
            "🔹 저장 폴더의 자동 생성\n"
            "저장 폴더가 존재하지 않는 경우 자동으로 생성됩니다. 생성 또는 저장 실패 시 권한 문제일 수 있습니다.\n"
        )
    def get_input_help(self):
        return (
            "📥 입력 경로 도움말\n\n"
            "🔹 파일 추가\n"
            "하나 이상의 이미지 파일을 선택합니다.\n\n"
            "🔹 폴더 추가\n"
            "선택한 폴더 내 이미지들을 자동으로 목록에 추가합니다.\n\n"
            "🔹 드래그 앤 드롭\n"
            "이미지 파일 또는 폴더를 목록에 직접 끌어다 놓을 수 있습니다.\n\n"
            "🔹 중복 삭제\n"
            "이미 추가된 파일은 다시 추가되지 않으며, 중복 알림이 표시됩니다.\n"
        )

    def get_listctrl_help(self):
        return (
            "📋 입력경로 리스트 사용법\n\n"
            "🔹 항목 선택\n"
            "Ctrl 또는 Shift 키로 여러 개를 선택할 수 있습니다.\n\n"
            "🔹 더블클릭\n"
            "선택한 이미지를 뷰어로 열 수 있습니다.\n\n"
            "🔹 마우스 오른쪽 클릭\n"
            "선택 항목을 삭제하는 메뉴가 표시됩니다.\n\n"
            "🔹 버튼 기능\n"
            "- 선택 삭제: 선택한 항목만 삭제\n"
            "- 전체 삭제: 모든 항목 삭제\n"
            "- 삭제 취소: 삭제 실행을 돌이킵니다.\n"
        )

    def get_image_viewer_help(self):
        return (
            "📋 이미지 뷰어 사용법\n\n"
            "🔹 버튼 기능\n"
            "- 처음/이전/다음/끝: 썸네일 내비게이션\n"
            "- 리스트에서 삭제: 썸네일 및 입력 리스트에서 해당 항목 삭제(실제 파일이 삭제되는 것은 아님).\n"
            "- 삭제 취소: '리스트에서 삭제'로 삭제된 항목 복원.\n\n"
            "🔹 단축키\n"
            "- 왼쪽/오른쪽 화살표: 버튼 '이전', '다음' 기능\n"
            "- Del: 버튼 '리스트에서 삭제' 기능\n"
            "- Ctrl+Z: 버튼 '삭제 취소' 기능\n"
            "- Esc(또는 이미지 더블클릭): 창 닫기\n"
            "- F1(또는 H): 도움말 열기\n"
        )


class ImageResizerFrame(wx.Frame):
    def __init__(self, parent, title):
        super().__init__(parent, title=title, size=(660, 580))
        #style = wx.DEFAULT_FRAME_STYLE & ~(wx.RESIZE_BORDER | wx.MAXIMIZE_BOX))

        ##self.thumbnail_size = (60, 60)
        self.input_paths = []
        self.undo_stack = []  # 삭제 기록 저장 (idx, path)
        self.stop_requested = False
        self.pids_explorer_existing = []

        # 설정 값 로드
        self.settings = self.load_settings()

        self.panel = wx.Panel(self)

        # 예: 툴바, 메뉴, 하단 도움말 버튼 등 원하는 위치에 추가
        self.help_center_btn = wx.Button(self.panel, label="도움말 📘")
        self.help_center_btn.Bind(wx.EVT_BUTTON, self.open_help_center)
        # 📦 블록 A: 레이블 + 리스트박스 (수직)

        self.input_path_label = wx.StaticText(self.panel, label="입력 경로: 0개의 이미지")

        self.input_listctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES)
        self.input_listctrl.SetMinSize((300, 235))
        self.input_listctrl.InsertColumn(0, "#", width=35)
        self.input_listctrl.InsertColumn(1, "형식", width=45)
        self.input_listctrl.InsertColumn(2, "파일 경로", width=1000)

        self.input_listctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_input_file_double_click)

        # 🔽 드래그앤드롭 대상 등록
        drop_target = FileDropHandler(self.input_listctrl, self.handle_dropped_files)
        self.input_listctrl.SetDropTarget(drop_target)

        # 📦 블록 B: 버튼 2개 (수직)

        self.input_file_button = wx.Button(self.panel, label="파일 추가")
        self.input_file_button.Bind(wx.EVT_BUTTON, self.browse_input_file)

        self.input_folder_button = wx.Button(self.panel, label="폴더 추가")
        self.input_folder_button.Bind(wx.EVT_BUTTON, self.browse_input_folder)

        self.remove_selected_button = wx.Button(self.panel, label="선택 삭제")
        self.remove_selected_button.Bind(wx.EVT_BUTTON, self.remove_selected_items)

        self.clear_list_button = wx.Button(self.panel, label="전체 삭제")
        self.clear_list_button.Bind(wx.EVT_BUTTON, self.clear_input_listctrl)

        self.undo_btn = wx.Button(self.panel, label="삭제 취소")
        self.undo_btn.Bind(wx.EVT_BUTTON, self.on_undo_delete)

        self.output_path_label = wx.StaticText(self.panel, label="출력 경로:")
        self.output_path_text = wx.TextCtrl(self.panel, style=wx.TE_READONLY)

        # 체크박스: 저장 전 폴더 비우기
        self.clear_folder_checkbox = wx.CheckBox(self.panel, label="저장 폴더 비우고 시작")
        self.clear_folder_checkbox.SetValue(self.settings["clear_folder"])

        self.output_button = wx.Button(self.panel, label="폴더 선택")
        self.output_button.Bind(wx.EVT_BUTTON, self.browse_output)

        self.open_output_btn = wx.Button(self.panel, label="폴더 열기")
        self.open_output_btn.Bind(wx.EVT_BUTTON, self.on_open_output_folder)

        """ 썸네일
        self.thumb_panel = wx.ScrolledWindow(self.panel, style=wx.HSCROLL)
        self.thumb_panel.SetMinSize((100, 88))
        self.thumb_panel.SetScrollRate(5, 0)

        self.thumb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.thumb_panel.SetSizer(self.thumb_sizer)
        """
        self.width_label = wx.StaticText(self.panel, label="너비(px):")
        self.width_entry = FloatSpin(self.panel, min_val=10, max_val=10000, increment=10, value=self.settings["max_width"], digits=0, size=(60, -1))
        self.width_entry.Bind(wx.EVT_TEXT, self.on_text_change)

        self.quality_label = wx.StaticText(self.panel, label="화질:")
        self.quality_entry = FloatSpin(self.panel, min_val=1, max_val=100, increment=5, value=self.settings["min_quality"], digits=0, size=(50, -1))
        self.quality_entry.Bind(wx.EVT_TEXT, self.on_quality_change)

        self.size_label = wx.StaticText(self.panel, label="용량(KB):")
        self.size_entry = FloatSpin(self.panel, min_val=10, max_val=10000, increment=10, value=self.settings["max_size_kb"], digits=0, size=(60, -1))
        self.size_entry.Bind(wx.EVT_TEXT, self.on_text_change)

        self.mode_label = wx.StaticText(self.panel, label="압축 모드:")
        self.mode_radio1 = wx.RadioButton(self.panel, label="화질", style=wx.RB_GROUP)
        self.mode_radio2 = wx.RadioButton(self.panel, label="용량")
        self.mode_radio1.SetValue(self.settings["mode"])
        self.mode_radio2.SetValue(not self.settings["mode"])
        if self.mode_radio1.GetValue():
            self.quality_label.Enable()
            self.quality_entry.Enable()
            self.size_label.Disable()
            self.size_entry.Disable()
        else:
            self.quality_label.Disable()
            self.quality_entry.Disable()
            self.size_label.Enable()
            self.size_entry.Enable()

        self.mode_radio1.Bind(wx.EVT_RADIOBUTTON, self.on_radio_selected)
        self.mode_radio2.Bind(wx.EVT_RADIOBUTTON, self.on_radio_selected)

        self.format_label = wx.StaticText(self.panel, label="출력 형식:")
        self.format_menu = wx.ComboBox(self.panel, choices=["JPEG", "PNG", "WebP", "원본 유지"], style=wx.CB_READONLY)
        self.format_menu.SetValue(self.settings["output_format"])
        if self.settings["output_format"] == 'PNG':
            self.quality_label.Disable()
            self.quality_entry.Disable()
            self.size_label.Disable()
            self.size_entry.Disable()
            self.mode_label.Disable()
            self.mode_radio1.Disable()
            self.mode_radio2.Disable()

        self.format_menu.Bind(wx.EVT_COMBOBOX, self.on_select)

        # 메인 수직 레이아웃에 추가
        # 상태 표시 & 진행바
        #self.status_text = wx.StaticText(self.panel, label="")
        self.status_text = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL | wx.VSCROLL)
        self.status_text.SetMinSize((300, 100))

        self.progress = wx.Gauge(self.panel, range=100, size=(300, -1))

        # ▶ 실행 버튼
        self.process_button = wx.Button(self.panel, label="▶ 이미지 처리 시작")
        self.process_button.Bind(wx.EVT_BUTTON, self.on_process_button_clicked)
        #self.process_button.Bind(wx.EVT_BUTTON, self.start_processing_thread)

        #self.stop_button = wx.Button(self.panel, label="⏹ 중지")
        #self.stop_button.Bind(wx.EVT_BUTTON, self.on_stop_clicked)
        #self.stop_button.Disable()

        self.SetIcon(wx.Icon("data/k-imageresizer.ico"))

        block_a = wx.BoxSizer(wx.VERTICAL)
        block_a.Add(self.input_path_label, 0, wx.BOTTOM | wx.LEFT, 5)
        block_a.Add(self.input_listctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        block_b = wx.BoxSizer(wx.VERTICAL)
        block_b.Add(self.help_center_btn, 0, wx.BOTTOM, 5)
        block_b.AddSpacer(20)  # self.input_file_button 상단 위치 조정
        block_b.Add(self.input_file_button, 0, wx.BOTTOM | wx.EXPAND, 5)
        block_b.Add(self.input_folder_button, 0, wx.BOTTOM | wx.EXPAND, 5)
        block_b.Add(self.remove_selected_button, 0, wx.BOTTOM | wx.EXPAND, 5)
        block_b.Add(self.clear_list_button, 0, wx.BOTTOM | wx.EXPAND, 5)
        block_b.Add(self.undo_btn, 0, wx.BOTTOM | wx.EXPAND, 5)

        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        row_sizer.Add(block_a, 1, wx.EXPAND | wx.ALL, 8)
        row_sizer.AddSpacer(0)  # A와 B 사이 간격
        row_sizer.Add(block_b, 0, wx.TOP | wx.BOTTOM | wx.RIGHT, 8)

        output_path_row = wx.BoxSizer(wx.HORIZONTAL)
        output_path_row.Add(self.output_path_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 8)
        output_path_row.Add(self.output_path_text, 1, wx.EXPAND | wx.RIGHT, 8)

        output_path_row2 = wx.BoxSizer(wx.HORIZONTAL)
        output_path_row2.Add((1,-1), 1, wx.EXPAND)
        output_path_row2.Add(self.output_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        output_path_row2.Add(self.open_output_btn, 0,wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)

        settings_row = wx.BoxSizer(wx.HORIZONTAL)
        settings_row.Add(self.width_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 2)
        settings_row.Add(self.width_entry, 1, wx.EXPAND | wx.RIGHT, 8)
        settings_row.Add(self.quality_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 2)
        settings_row.Add(self.quality_entry, 1, wx.EXPAND | wx.RIGHT, 8)
        settings_row.Add(self.size_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 2)
        settings_row.Add(self.size_entry, 1, wx.EXPAND | wx.RIGHT, 8)
        settings_row.Add(self.mode_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 2)
        settings_row.Add(self.mode_radio1, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        settings_row.Add(self.mode_radio2, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
        settings_row.Add(self.format_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 2)
        settings_row.Add(self.format_menu, 1, wx.EXPAND | wx.RIGHT, 8)

        process = wx.BoxSizer(wx.HORIZONTAL)
        process.Add(self.clear_folder_checkbox, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 10)
        process.Add(self.process_button, 1, wx.EXPAND | wx.LEFT, 8)

        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.sizer.Add(row_sizer, 0, wx.EXPAND | wx.ALL, 0)
        #### 썸네일self.sizer.Add(self.thumb_panel, 0, wx.EXPAND | wx.ALL, 0)
        self.sizer.Add(output_path_row, 0, wx.EXPAND | wx.ALL, 5)
        self.sizer.Add(output_path_row2, 0, wx.EXPAND | wx.BOTTOM | wx.LEFT | wx.RIGHT, 5)
        self.sizer.Add(settings_row, 0, wx.EXPAND | wx.ALL, 5)
        self.sizer.Add(self.status_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        self.sizer.Add(self.progress, 0, wx.EXPAND | wx.ALL, 10)
        self.sizer.Add(process, 0, wx.EXPAND | wx.BOTTOM | wx.RIGHT, 10)
        #self.sizer.Add(self.stop_button, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self.sizer.Layout()
        self.panel.SetSizer(self.sizer)
        self.Centre()
        self.Show()
        self.process_button.SetDefault()  # 프레임 초기화 시에도 Enter 키로 작동하도록

        # 컨텍스트 메뉴 이벤트
        self.input_listctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
        """ 썸네일
        self.input_listctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_list_item_selected)
        self.input_listctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_list_item_deselected)
        """
        self.Bind(wx.EVT_CLOSE, self.onwindow_close)
        for proc in psutil.process_iter(['pid', 'name']):
            if proc.info['name'] == 'explorer.exe':
                self.pids_explorer_existing.append(proc.info['pid'])

    def on_radio_selected(self, event):
        radio_label = event.GetEventObject().GetLabel()
        if radio_label == '화질':
            self.quality_label.Enable()
            self.quality_entry.Enable()
            self.size_label.Disable()
            self.size_entry.Disable()
        else:
            self.quality_label.Disable()
            self.quality_entry.Disable()
            self.size_label.Enable()
            self.size_entry.Enable()

    def on_select(self, event):
        format_menu = self.format_menu.GetValue()
        if format_menu == 'PNG':
            self.quality_label.Disable()
            self.quality_entry.Disable()
            self.size_label.Disable()
            self.size_entry.Disable()
            self.mode_label.Disable()
            self.mode_radio1.Disable()
            self.mode_radio2.Disable()

        else:
            if self.mode_radio1.GetValue():
                self.quality_label.Enable()
                self.quality_entry.Enable()
                self.size_label.Disable()
                self.size_entry.Disable()
            else:
                self.quality_label.Disable()
                self.quality_entry.Disable()
                self.size_label.Enable()
                self.size_entry.Enable()

            self.mode_label.Enable()
            self.mode_radio1.Enable()
            self.mode_radio2.Enable()

    def get_selected_mode(self):
        return 1 if self.mode_radio1.GetValue() else 0

    def on_text_change(self, event):
        textctrl = event.GetEventObject()
        value = textctrl.GetValue()

        # 정규식 검사: 1 이상의 정수, 앞자리 0 금지
        if re.fullmatch(r'[1-9]\d*', value):
            textctrl.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        else:
            textctrl.SetBackgroundColour("pink")

        textctrl.Refresh()

    def on_quality_change(self, event):
        """Quality 입력값 검증: 1~100 정수, 앞자리 0 금지"""
        textctrl = event.GetEventObject()
        value = textctrl.GetValue()

        if re.fullmatch(r'[1-9]\d{0,1}|100', value):  # 1~99 또는 100
            textctrl.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))
        else:
            textctrl.SetBackgroundColour("pink")

        textctrl.Refresh()

    def on_process_button_clicked(self, event):
        if self.process_button.GetLabel() == "▶ 이미지 처리 시작":
            self.start_processing_thread(event)
        else:
            self.on_stop_clicked(event)

    def on_stop_clicked(self, event=None):
        self.stop_requested = True
        self.log_status("⏹ 처리 중지 요청됨.")
        self.process_button.SetLabel("▶ 이미지 처리 시작")

    """
    def on_stop_clicked(self, event):
        self.stop_requested = True
        self.log_status("⛔️ 처리 중단 요청됨")
    """
    def on_undo_delete(self, event):
        if not self.undo_stack:
            wx.MessageBox("되돌릴 삭제 항목이 없습니다.", "정보", wx.ICON_INFORMATION)
            return

        deleted = self.undo_stack.pop()
        for idx, format_name, path in sorted(deleted):
            self.input_listctrl.InsertItem(idx, str(idx + 1))
            self.input_listctrl.SetItem(idx, 1, format_name)
            self.input_listctrl.SetItem(idx, 2, path)

        # 번호 다시 매기기
        for i in range(self.input_listctrl.GetItemCount()):
            self.input_listctrl.SetItem(i, 0, str(i + 1))

        #### 썸네일self.update_list_thumbnails()
        self.update_input_path_label()

    """ 썸네일
    def on_list_item_selected(self, event):
        self.update_thumbnail_highlight()
        event.Skip()

    def on_list_item_deselected(self, event):
        wx.CallAfter(self.update_thumbnail_highlight)
        event.Skip()

    def update_thumbnail_highlight(self):
        list_count = self.input_listctrl.GetItemCount()
        thumb_count = len(self.thumbnails)

        for i in range(min(list_count, thumb_count)):
            if self.input_listctrl.IsSelected(i):
                self.thumbnails[i].SetBackgroundColour(wx.Colour(30, 144, 255))  # 선택 강조
            else:
                self.thumbnails[i].SetBackgroundColour(wx.Colour(240, 240, 240))  # 기본 색

            self.thumbnails[i].Refresh()

        # 혹시 썸네일이 리스트보다 더 많으면 남은 건 비활성 처리
        for i in range(list_count, thumb_count):
            self.thumbnails[i].SetBackgroundColour(wx.Colour(240, 240, 240))
            self.thumbnails[i].Refresh()

    def update_list_thumbnails(self):
        # 기존 썸네일 삭제
        for child in self.thumb_panel.GetChildren():
            child.Destroy()
        self.thumbnails = []

        for idx in range(self.input_listctrl.GetItemCount()):
            path = self.input_listctrl.GetItemText(idx, 1)

            try:
                img = PILImage.open(path)
                img.thumbnail(self.thumbnail_size)

                wx_img = wx.Image(img.width, img.height)
                wx_img.SetData(img.convert("RGB").tobytes())
                bmp = wx.Bitmap(wx_img)

                # 🔽 여기서 thumb_panel 생성
                thumb_panel = wx.Panel(self.thumb_panel, size=(self.thumbnail_size[0]+8, self.thumbnail_size[1]+8))
                thumb_panel.SetBackgroundColour(wx.Colour(240, 240, 240))  # 기본 배경

                # StaticBitmap 생성 및 배치
                thumb_bitmap = wx.StaticBitmap(thumb_panel, bitmap=bmp)
                thumb_bitmap.Center()

                # 이벤트 바인딩 (토글용)
                self.bind_thumb_event(thumb_panel, idx)

                # self.thumbnails 리스트에 등록
                self.thumbnails.append(thumb_panel)

                # 썸네일 레이아웃에 추가
                self.thumb_sizer.Add(thumb_panel, 0, wx.ALL, 4)

            except Exception as e:
                print(f"썸네일 생성 실패: {path} - {e}")

        self.thumb_panel.Layout()
        self.thumb_panel.FitInside()
        self.thumb_panel.SetVirtualSize(self.thumb_sizer.GetMinSize())

    def bind_thumb_event(self, panel, idx):
        def handler(event):
            self.on_thumb_click(idx)
            event.Skip()  # 다른 핸들러도 실행될 수 있게 허용

        panel.Bind(wx.EVT_LEFT_DOWN, handler)

        # 모든 자식에도 같은 이벤트 바인딩
        for child in panel.GetChildren():
            child.Bind(wx.EVT_LEFT_DOWN, handler)

    def on_thumb_click(self, idx):
        if self.input_listctrl.IsSelected(idx):
            self.input_listctrl.Select(idx, on=0)  # 선택 해제
        else:
            self.input_listctrl.Select(idx)  # 선택
            self.input_listctrl.Focus(idx)  # 포커스도 이동

        #### 썸네일self.update_thumbnail_highlight()
    """
    def log_status(self, message, clear=False):
        timestamp = time.strftime("[%H:%M:%S] ")
        if clear:
            self.status_text.SetValue("")  # 로그 전체 지우기
        self.status_text.AppendText(timestamp + message + "\n")
        self.status_text.ShowPosition(self.status_text.GetLastPosition())  # 자동 스크롤

    def open_help_center(self, event):
        dlg = HelpCenterDialog(self)
        dlg.ShowModal()

    def handle_dropped_files(self, file_paths):
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.webp', '.bmp', '.avif', '.gif', '.ico')
        existing_items = [self.input_listctrl.GetItemText(i, 2) for i in range(self.input_listctrl.GetItemCount())]

        new_items = []
        duplicate_items = []

        for path in file_paths:
            if not path.lower().endswith(image_extensions):
                continue
            if path not in existing_items:
                new_items.append(path)
            else:
                duplicate_items.append(path)

        if duplicate_items:
            wx.MessageBox(f"{len(duplicate_items)}개의 파일은 이미 추가되어 있습니다.", "중복 항목", wx.ICON_INFORMATION)

        if new_items:
            for path in new_items:
                index = self.input_listctrl.GetItemCount()
                ext = os.path.splitext(path)[1].lower().replace('.', '')
                format_name = ext.upper().replace('JPG', 'JPEG').replace('WEBP', 'WebP')

                self.input_listctrl.InsertItem(index, str(index + 1))
                self.input_listctrl.SetItem(index, 1, format_name)
                self.input_listctrl.SetItem(index, 2, path)

            Toast(self, f"{len(new_items)}개 추가됨.", 1000)
            self.update_input_path_label()
            #### 썸네일self.update_list_thumbnails()

    def on_open_output_folder(self, event):
        path = self.output_path_text.GetValue()
        if path and os.path.isdir(path):
            self.cleanup_explorer()
            Popen(f'explorer "{path}"')
        else:
            wx.MessageBox("유효한 출력 폴더가 설정되어 있지 않습니다.", "알림", wx.ICON_INFORMATION)

    def remove_selected_items(self, event):
        selected_indices = []
        index = self.input_listctrl.GetFirstSelected()
        while index != -1:
            selected_indices.append(index)
            index = self.input_listctrl.GetNextSelected(index)

        if not selected_indices:
            wx.MessageBox("삭제할 항목을 선택하세요.", "알림", wx.ICON_INFORMATION)
            return

        deleted = []
        for idx in reversed(selected_indices):
            format_name = self.input_listctrl.GetItemText(idx, 1)
            path = self.input_listctrl.GetItemText(idx, 2)
            deleted.append((idx, format_name, path))
            self.input_listctrl.DeleteItem(idx)

        self.undo_stack.append(deleted)

        # 번호 다시 매기기
        for i in range(self.input_listctrl.GetItemCount()):
            self.input_listctrl.SetItem(i, 0, str(i + 1))

        Toast(self, f"{len(selected_indices)}개 삭제됨")
        self.update_input_path_label()
        #### 썸네일self.update_list_thumbnails()

    def clear_input_listctrl(self, event):
        item_count = self.input_listctrl.GetItemCount()
        if item_count == 0:
            wx.MessageBox("입력경로 목록이 비었습니다.", "알림", wx.ICON_INFORMATION)
            return

        deleted = []
        for idx in range(item_count):
            format_name = self.input_listctrl.GetItemText(idx, 1)
            path = self.input_listctrl.GetItemText(idx, 2)
            deleted.append((idx, format_name, path))

        self.input_listctrl.DeleteAllItems()
        self.undo_stack.append(deleted)
        self.update_input_path_label()
        #### 썸네일self.update_list_thumbnails()

    def on_context_menu(self, event):
        menu = wx.Menu()
        delete_item = menu.Append(wx.ID_DELETE, "선택 삭제")
        self.Bind(wx.EVT_MENU, self.remove_selected_items, delete_item)
        self.PopupMenu(menu)
        menu.Destroy()

    def browse_input_folder(self, event):
        image_extensions = ('.jpg', '.jpeg', '.png', '.tiff', '.webp', '.bmp', '.avif', '.gif', '.ico')

        with wx.DirDialog(self, "입력 폴더 선택", style=wx.DD_DEFAULT_STYLE) as dirDialog:
            if dirDialog.ShowModal() == wx.ID_OK:
                folder_path = dirDialog.GetPath()

                image_files = []
                for filename in os.listdir(folder_path):
                    full_path = os.path.join(folder_path, filename)
                    if os.path.isfile(full_path) and full_path.lower().endswith(image_extensions):
                        image_files.append(full_path)

                # 기존 리스트 항목 가져오기 (파일 경로만 추출)
                existing_items = [
                    self.input_listctrl.GetItem(i, 2).GetText()
                    for i in range(self.input_listctrl.GetItemCount())
                ]

                # 중복 확인
                new_items = []
                duplicate_items = []

                for path in image_files:
                    if path not in existing_items:
                        new_items.append(path)
                    else:
                        duplicate_items.append(path)

                if duplicate_items:
                    msg = f"{len(duplicate_items)}개의 파일은 이미 추가되어 있습니다."
                    wx.MessageBox(msg, "중복 항목", wx.ICON_INFORMATION)

                if new_items:
                    current_count = self.input_listctrl.GetItemCount()
                    for i, path in enumerate(new_items):
                        index = current_count + i
                        # 파일 형식 추출 (예: JPEG, PNG, WebP)
                        ext = os.path.splitext(path)[1].lower().replace('.', '')  # 확장자만
                        format_name = ext.upper().replace('JPG', 'JPEG').replace('WEBP', 'WebP')
                        self.input_listctrl.InsertItem(index, str(index + 1))  # 번호 열
                        self.input_listctrl.SetItem(index, 1, format_name)
                        self.input_listctrl.SetItem(index, 2, path)  # 파일 경로 열

                    Toast(self, f"{len(new_items)}개 추가됨.", 1000)
                    self.update_input_path_label()
                    #### 썸네일self.update_list_thumbnails()

    def browse_input_file(self, event):
        with wx.FileDialog(
                self, "이미지 파일 선택",
                wildcard="이미지 파일 (*.jpg;*.jpeg;*.png;*.tiff;*.webp;*.bmp;*.avif;*.gif;*.ico)|"
                         "*.jpg;*.jpeg;*.png;*.tiff;*.webp;*.bmp;*.avif;*.gif;*.ico",
                style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE
        ) as fileDialog:
            if fileDialog.ShowModal() == wx.ID_OK:
                file_paths = fileDialog.GetPaths()

                # 기존 항목 추출 (파일 경로 기준)
                existing_items = [
                    self.input_listctrl.GetItem(i, 2).GetText()  # 두 번째 열: 파일 경로
                    for i in range(self.input_listctrl.GetItemCount())
                ]

                # 중복 확인
                new_items = []
                duplicate_items = []

                for path in file_paths:
                    if path not in existing_items:
                        new_items.append(path)
                    else:
                        duplicate_items.append(path)

                if duplicate_items:
                    msg = f"{len(duplicate_items)}개의 파일은 이미 추가되어 있습니다."
                    wx.MessageBox(msg, "중복 항목", wx.ICON_INFORMATION)

                if new_items:
                    current_count = self.input_listctrl.GetItemCount()
                    for i, path in enumerate(new_items):
                        index = current_count + i
                        # 파일 형식 추출 (예: JPEG, PNG, WebP)
                        ext = os.path.splitext(path)[1].lower().replace('.', '')  # 확장자만
                        format_name = ext.upper().replace('JPG', 'JPEG').replace('WEBP', 'WebP')
                        self.input_listctrl.InsertItem(index, str(index + 1))  # 열 0: 번호
                        self.input_listctrl.SetItem(index, 1, format_name)
                        self.input_listctrl.SetItem(index, 2, path)  # 열 1: 파일 경로

                    Toast(self, f"{len(new_items)}개 추가됨.", 1000)
                    self.update_input_path_label()
                    #### 썸네일self.update_list_thumbnails()

    def update_input_path_label(self):
        count = self.input_listctrl.GetItemCount()
        self.input_path_label.SetLabel(f"입력 경로: {count}개의 이미지")

        if count > 0:
            first_path = self.input_listctrl.GetItemText(0, 2)
            if os.path.isfile(first_path):
                base_folder = os.path.dirname(first_path)
            elif os.path.isdir(first_path):
                base_folder = first_path
            else:
                base_folder = os.getcwd()

            output_path = os.path.join(base_folder, "출력")
            if not self.output_path_text.GetValue():
                if not os.path.exists(output_path):
                    os.makedirs(output_path)
                self.output_path_text.SetValue(output_path)

    def browse_output(self, event):
        dialog = wx.DirDialog(self, "출력폴더 선택", style=wx.DD_DEFAULT_STYLE)
        if dialog.ShowModal() == wx.ID_OK:
            self.output_path_text.SetValue(dialog.GetPath())
            self.process_button.SetFocus()  # ✅ 포커스 이동
            self.process_button.SetDefault()  # ✅ Enter 키 기본 동작으로 설정
        dialog.Destroy()

    def resize_image_keep_ratio(self, img, base_width):
        if img.width <= base_width:
            return img
        w_percent = base_width / float(img.size[0])
        h_size = int(float(img.size[1]) * w_percent)
        return img.resize((base_width, h_size), PILImage.LANCZOS)

    def compress_and_save(self, img, output_path, format_name, min_quality, max_kb, mode):
        def get_size_kb(path):
            return os.path.getsize(path) / 1024

        mid = None
        best_params = None

        if format_name in ["JPEG", "JPG"]:
            if mode == 1:
                try:
                    img.save(output_path, format="JPEG", quality=min_quality, optimize=True)
                except OSError:
                    img.save(output_path, format="JPEG", quality=min_quality)

                size_kb = get_size_kb(output_path)
                return f"[화질 우선] quality={min_quality}, size={round(size_kb)}KB"
            else:
                min_quality = 1 # 용량 우선이므로 화질을 1로 간주
                low, high = 10, 100
                while low <= high:
                    if self.stop_requested:
                        return
                    mid = (low + high) // 2
                    if mid < min_quality:
                        low = mid + 1
                        continue

                    try:
                        img.save(output_path, format="JPEG", quality=mid, optimize=True)
                    except OSError:
                        img.save(output_path, format="JPEG", quality=mid)

                    size_kb = get_size_kb(output_path)
                    if size_kb <= max_kb:
                        best_params = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                if best_params:
                    img.save(output_path, format="JPEG", quality=best_params, optimize=True)
                    return f"[용량 우선] quality={best_params}, size={round(get_size_kb(output_path))}KB"
                else:
                    return f"최적 품질 찾기 실패 (마지막 시도: quality={mid})"

        elif format_name == "PNG":
            compress_level = 9
            try:
                img.save(output_path, format="PNG", compress_level=compress_level, optimize=True)
            except OSError:
                img.save(output_path, format="PNG", compress_level=compress_level)

            return f"[무손실] compress_level={compress_level}, size={round(get_size_kb(output_path))}KB"

        elif format_name == "WebP":
            if mode == 1:
                try:
                    img.save(output_path, format="WebP", quality=min_quality, method=6)
                except OSError:
                    img.save(output_path, format="WebP", quality=min_quality)

                return f"[화질 우선] quality={min_quality}, size={round(get_size_kb(output_path))}KB"
            else:
                min_quality = 1 # 용량 우선이므로 화질을 1로 간주
                low, high = 10, 100
                while low <= high:
                    if self.stop_requested:
                        return

                    mid = (low + high) // 2
                    if mid < min_quality:
                        low = mid + 1
                        continue

                    try:
                        img.save(output_path, format="WebP", quality=mid, method=6)
                    except OSError:
                        img.save(output_path, format="WebP", quality=mid)

                    size_kb = get_size_kb(output_path)
                    if size_kb <= max_kb:
                        best_params = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                if best_params:
                    img.save(output_path, format="WebP", quality=best_params, method=6)
                    return f"[용량 우선] quality={best_params}, size={round(get_size_kb(output_path))}KB"

        elif format_name == "AVIF":
            if mode == 1:
                try:
                    img.save(output_path, format="AVIF", quality=min_quality, speed=0)
                    return f"[화질 우선] quality={min_quality}, size={round(get_size_kb(output_path))}KB"
                except Exception as e:
                    print(f"AVIF 저장 실패: {e}")
                    self.log_status(f"AVIF 저장 실패: {e}")
                    return False
            else:
                min_quality = 1 # 용량 우선이므로 화질을 1로 간주
                low, high = 10, 100
                while low <= high:
                    if self.stop_requested:
                        return

                    mid = (low + high) // 2
                    if mid < min_quality:
                        low = mid + 1
                        continue

                    try:
                        img.save(output_path, format="AVIF", quality=mid, speed=0)
                    except Exception as e:
                        print(f"AVIF 저장 실패: {e}")
                        self.log_status(f"AVIF 저장 실패: {e}")
                        break

                    if get_size_kb(output_path) <= max_kb:
                        best_params = mid
                        low = mid + 1
                    else:
                        high = mid - 1

                if best_params:
                    img.save(output_path, format="AVIF", quality=best_params, speed=0)
                    return f"[용량 우선] quality={best_params}, size={round(get_size_kb(output_path))}KB"

        elif format_name == "TIFF":
            try:
                img.save(output_path, format="TIFF", compression="tiff_lzw")
                return f"compression=tiff_lzw, size={round(get_size_kb(output_path))}KB"
            except Exception as e:
                print(f"TIFF 저장 실패: {e}")
                self.log_status(f"TIFF 저장 실패: {e}")
                return False

        elif format_name == "BMP":
            try:
                img.save(output_path, format="BMP")
                return f"[무압축] size={round(get_size_kb(output_path))}KB"
            except Exception as e:
                print(f"BMP 저장 실패: {e}")
                self.log_status(f"BMP 저장 실패: {e}")
                return False

        else:
            try:
                img.save(output_path, format=format_name)
                return f"[무압축] size={round(get_size_kb(output_path))}KB"
            except Exception as e:
                print(f"저장 실패 ({format_name}): {e}")
                self.log_status(f"저장 실패 ({format_name}): {e}")
                return False

    def process_images(self, input_paths, output_folder, max_width, min_quality, max_size_kb, output_format, mode):
        self.stop_requested = False  # 시작 전 초기화
        image_files = []

        for input_path in input_paths:
            if os.path.isfile(input_path):
                image_files.append(input_path)
            elif os.path.isdir(input_path):
                image_files.extend([
                    os.path.join(input_path, f)
                    for f in os.listdir(input_path)
                    if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                ])

        self.progress.SetRange(len(image_files))
        processed = 0

        for idx, input_file in enumerate(image_files):
            if self.stop_requested:
                break

            input_ext = os.path.splitext(os.path.basename(input_file))[1]
            if output_format == '원본 유지':
                output_name = os.path.basename(input_file)
            else:
                output_name = os.path.splitext(os.path.basename(input_file))[0] + "." + output_format.lower()

            output_path = os.path.join(output_folder, output_name)
            output_path = normalize_extension(output_path, output_format)
            try:
                with PILImage.open(input_file) as img:
                    img = ImageOps.exif_transpose(img)

                    if img.mode != 'RGB':
                        img = img.convert('RGB')

                    # ✅ 원본 유지 조건: 입/출력 동일 형식 & 너비,용량 모두 기준 이하
                    input_ext_ = input_ext.replace('.', '').lower().replace('jpeg', 'jpg')
                    if output_format == '원본 유지':
                        output_ext = os.path.splitext(os.path.basename(input_file))[1].replace('.', '')
                        output_format_ = output_ext.upper().replace('JPG', 'JPEG').replace('WEBP', 'WebP')
                    else:
                        output_ext = output_format.lower().replace('jpeg', 'jpg')
                        output_format_ = output_format

                    if input_ext_ == output_ext and img.width <= max_width and os.path.getsize(input_file) <= max_size_kb * 1024:
                        shutil.copy2(input_file, output_path)
                        processed += 1
                        print(f"{idx+1}. ⮕ ✅ 원본 복사:	{os.path.basename(output_path)}")
                        self.log_status(f"{idx+1}. ⮕ ✅ 원본 복사:			{os.path.basename(output_path)}")

                    else:
                        img = self.resize_image_keep_ratio(img, max_width)
                        success = self.compress_and_save(img, output_path, output_format_, min_quality, max_size_kb, mode)

                        if success:
                            processed += 1
                            self.log_status(f"{idx+1}. ⮕ {success}:	{os.path.basename(output_path)}")
                        else:
                            print(f"{idx+1}. ⮕ ⚠️ 압축 실패: {input_file}")
                            self.log_status(f"{idx+1}. ⮕ ⚠️ 압축 실패: {input_file}")


            except Exception as e:
                e_ = f"{e}".replace("\\\\", "\\")
                print(f"{idx+1}. ⮕ ❌ 오류: {input_file} - {e_}")
                self.log_status(f"{idx+1}. ⮕ ❌ 오류: {input_file} - {e_}")
                wx.MessageBox(f"{idx+1}. ⮕ ❌ 오류: {os.path.basename(input_file)}", "오류", wx.ICON_ERROR)


            self.progress.SetValue(idx + 1)
            self.Refresh()
            self.Update()

        return processed

    def start_processing_thread(self, event):
        threading.Thread(target=self.start_processing).start()

    def start_processing(self):
        # ✅ 줄 단위로 분리
        input_paths = [self.input_listctrl.GetItemText(i, 2) for i in range(self.input_listctrl.GetItemCount())]
        if not input_paths:
            wx.MessageBox("입력 경로 리스트가 비었습니다.", "알림", wx.ICON_INFORMATION)
            return

        self.stop_requested = False
        self.process_button.SetLabel("⏹ 중지")

        output_path = self.output_path_text.GetValue()
        if output_path:
            if not os.path.exists(output_path):
                os.makedirs(output_path)
        else:
            first_input = input_paths[0]

            if os.path.isfile(first_input):
                base_folder = os.path.dirname(first_input)
            elif os.path.isdir(first_input):
                base_folder = first_input
            else:
                base_folder = os.getcwd()  # fallback

            output_path = os.path.join(base_folder, "출력")

            if not os.path.exists(output_path):
                os.makedirs(output_path)

            self.output_path_text.SetValue(output_path)

        if self.clear_folder_checkbox.IsChecked():
            output_path = self.output_path_text.GetValue()
            clear_folder(output_path)

        format_name = self.format_menu.GetValue()

        try:
            width = int(self.width_entry.GetValue())
            size_kb = int(self.size_entry.GetValue())
            quality = int(self.quality_entry.GetValue())
            mode = self.get_selected_mode()
        except ValueError:
            wx.MessageBox("숫자(정수)를 정확히 입력하세요!", "오류", wx.ICON_ERROR)
            return

        #self.stop_button.Enable()
        #self.process_button.Disable()

        self.log_status("이미지 처리 시작", clear=True)
        #self.log_status("처리 중입니다...")
        self.progress.SetValue(0)

        count = self.process_images(input_paths, output_path, width, quality, size_kb, format_name, mode)

        if self.stop_requested:
            self.log_status("🚫 처리 중지됨")
            self.progress.SetValue(0)

        #self.stop_button.Disable()  # 혹은 Enable/Disable 로 제어
        #self.process_button.Enable()

        if not self.stop_requested:
            self.log_status(f"{count}개의 이미지 처리 완료")

            # 출력폴더 열기
            if count > 0:
                wx.CallAfter(Toast, None, f"{count}개의 이미지가 처리되었습니다!", 1000)
                self.open_output_folder(output_path)
            else:
                wx.MessageBox("0개의 이미지가 처리되었습니다!", "완료", wx.ICON_INFORMATION)
        else:
            self.stop_requested = False  # 처리 끝나고 초기화
            wx.MessageBox("이미지 처리가 중지되었습니다.", "중지", wx.ICON_INFORMATION)

        self.process_button.SetLabel("▶ 이미지 처리 시작")

        # 설정 저장
        self.settings["max_width"] = width
        self.settings["max_size_kb"] = size_kb
        self.settings["min_quality"] = quality
        self.settings["output_format"] = format_name
        self.settings["clear_folder"] = self.clear_folder_checkbox.IsChecked()
        self.settings["mode"] = mode
        self.save_settings()

    def open_output_folder(self, output_path):
        self.cleanup_explorer()
        # 탐색기에서 이미 해당 폴더가 열려있는지 확인하는 방식은 제한적이지만
        # Windows에서 폴더 열기
        Popen(f'explorer "{output_path}"')  # Windows 탐색기에서 폴더 열기

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        else:
            return DEFAULT_SETTINGS

    def save_settings(self):
        with open(SETTINGS_FILE, "w") as f:
            json.dump(self.settings, f)

    def on_input_file_double_click(self, event):
        item_index = event.GetIndex()
        if item_index != wx.NOT_FOUND:
            # 전체 파일 목록을 가져오기
            self.input_paths = [self.input_listctrl.GetItemText(i, 2) for i in range(self.input_listctrl.GetItemCount())]

            try:
                self.open_image_viewer(item_index)
            except Exception as e:
                e_ = f"{e}".replace("\\\\", "\\")
                path = self.input_listctrl.GetItemText(item_index, 2)
                print(f"❌ 파일 열기 실패: {path} - {e_}")
                wx.MessageBox(f"❌ 파일 열기 실패: {os.path.basename(path)}", "오류", wx.ICON_ERROR)

    def update_numbering(self):
        for idx in range(self.input_listctrl.GetItemCount()):
            self.input_listctrl.SetItem(idx, 0, str(idx + 1))  # No. 열은 0번

    def open_image_viewer(self, start_index=0):
        splash_bitmap = wx.Image("./data/splash.jpg").ConvertToBitmap()
        # 스플래시 설정 (timeout=0이면 수동으로 닫음)
        splash = wx.adv.SplashScreen(
            splash_bitmap,
            wx.adv.SPLASH_CENTRE_ON_SCREEN | wx.adv.SPLASH_NO_TIMEOUT,
            0,
            None,
            -1
        )

        wx.Yield()  # 스플래시가 보이도록 GUI 이벤트 순환
        viewer = ImageViewerFrame(
            parent=self,
            title="이미지 뷰어",
            images=self.input_paths,
            start_index=start_index,
            on_delete_callback=self.handle_delete,
            on_restore_callback=self.restore_to_list,
            splash=splash
        )

    def handle_delete(self, path):
        # 내부 리스트에서 삭제 (있다면)
        if path in self.input_paths:
            self.input_paths.remove(path)

        # 리스트컨트롤에서 삭제 (1번 열: 파일 경로 기준)
        for idx in range(self.input_listctrl.GetItemCount()):
            item_path = self.input_listctrl.GetItemText(idx, 2)
            if item_path == path:
                self.input_listctrl.DeleteItem(idx)
                format_name = self.input_listctrl.GetItemText(idx, 1)
                self.undo_stack.append([(idx, format_name, path)])
                break

        # 🔢 No. 열 다시 채우기
        self.update_numbering()
        self.update_input_path_label()

        #### 썸네일self.update_list_thumbnails()

    def restore_to_list(self, path, index):
        deleted = self.undo_stack.pop()
        format_name = deleted[0][1]

        # 리스트에 삽입
        self.input_listctrl.InsertItem(index, str(index + 1))  # No.
        self.input_listctrl.SetItem(index, 1, format_name)  # 형식
        self.input_listctrl.SetItem(index, 2, path)  # 경로

        # 전체 항목 No. 다시 정렬
        for i in range(self.input_listctrl.GetItemCount()):
            self.input_listctrl.SetItem(i, 0, str(i + 1))

        self.update_input_path_label()

        # 썸네일도 업데이트
        #### 썸네일 self.update_list_thumbnails()

    def cleanup_explorer(self):
        # 현재 실행 중인 explorer.exe 중 기존에 있던 것이 아닌 것만 대상으로 함
        procs_to_terminate = [
            proc for proc in psutil.process_iter(['name', 'pid'])
            if proc.info['name'] == 'explorer.exe' and proc.info['pid'] not in self.pids_explorer_existing
        ]

        # 프로세스 종료 시도
        for proc in procs_to_terminate:
            try:
                proc.terminate()
            except Exception as e:
                print(f"Error terminating {proc.pid}: {e}")

        # 종료 확인: 최대 5초까지 기다림
        gone, alive = psutil.wait_procs(procs_to_terminate, timeout=5)

        for proc in alive:
            try:
                proc.kill()  # 강제 종료
            except Exception as e:
                print(f"Error killing {proc.pid}: {e}")

        # 최종적으로 모두 종료되었는지 재확인
        for proc in procs_to_terminate:
            try:
                p = psutil.Process(proc.pid)
                if p.is_running():
                    print(f"Process {proc.pid} is still running.")
                else:
                    print(f"Process {proc.pid} terminated.")
            except psutil.NoSuchProcess:
                print(f"Process {proc.pid} has been terminated.")

    def onwindow_close(self, evt):
        self.cleanup_explorer()
        evt.Skip()


class ImageResizerApp(wx.App):
    def OnInit(self):
        self.frame = ImageResizerFrame(None, title="K-ImageResizer")
        return True


if __name__ == "__main__":
    app = ImageResizerApp(False)
    app.MainLoop()
