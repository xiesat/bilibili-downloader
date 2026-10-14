from tkinter import *
import tk_main


def main():
    root = Tk()
    root.title('bilibili视频提取')
    root.geometry('800x250')
    app = tk_main.Application(master=root)
    app.mainloop()
    root.destroy()
    return 0

main()