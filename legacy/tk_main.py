from tkinter import *
from tkinter.filedialog import askdirectory
import paqu_main
import os


class Application(Frame):
    
    url = ''
    btav= [0,0,0,0]
    def __init__(self, master=None):
        Frame.__init__(self, master)
        self.pack()
        self.createWidgets()

    def v_name(self):
        self.btav[0] = self.search_text3.get()
        label7.configure(text='确认完成')
        pass
    def url_pq(self):
        
        p_text = paqu_main.req(self.url,paqu_main.headers)
        a = list(paqu_main.fen_xi(page_text=p_text))  
        for i in range(3):
            self.btav[i] = a[i]
        pass

    def getEntry(self):
        bv = self.search_text1.get()
        self.url = 'https://www.bilibili.com/video/'+bv+'/'
        self.url_pq()
        label2.configure(text=self.btav[0])

    def dwon(self):
        if self.btav[0] != 0:
            paqu_main.down(btva=self.btav)
            label3.configure(text='下载完成')
        else:
            label6.configure(text='请先输入视频信息')    
    
    def down_wz(self):
        wz = self.search_text2.get()
        if wz != '':
            self.btav[3] = wz
            label4.configure(text='下载地址确认完成')
        else:
            label6.configure(text='请输入正确下载地址')
        pass

    def selectPath(self):
        path_ = askdirectory() #使用askdirectory()方法返回文件夹的路径
        if path_ == "":
            self.path.get() #当打开文件路径选择框后点击"取消" 输入框会清空路径，所以使用get()方法再获取一次路径
            self.btav[3] = str(path_)
        else:
            path_ = path_.replace("/", "\\")  # 实际在代码中执行的路径为“\“ 所以替换一下
            self.path.set(path_)
            self.btav[3] = str(path_)


    def createWidgets(self):
        self.search_text1 = StringVar()
        self.search_text2 = StringVar()
        self.search_text3 = StringVar()
        self.path = StringVar()
        self.path.set(os.path.abspath("."))
        global label2,label3,label4,label6,label7

        self.label1 = Label(self,text='下载视频bv号\n(1先输入)：',font=('微软雅黑', 12),height=2)
        self.label1.grid(row=1,column=1)
        self.label1 = Label(self,text='下载视频名字\n(不输入即为默认)：',font=('微软雅黑', 12),height=2)
        self.label1.grid(row=3,column=1)
        self.label5 = Label(self,text='目标位置(不输入即为默认)：',font=('微软雅黑', 12),height=2)
        self.label5.grid(row=2,column=1)
        
        label2 = Label(self,text='',font=('微软雅黑', 12),height=2)
        label2.grid(row=4,column=4)
        label3 = Label(self,text='',font=('微软雅黑', 12),height=2)
        label3.grid(row=4,column=1)
        label4 = Label(self,text='',font=('微软雅黑', 12),height=2)
        label4.grid(row=2,column=4)
        label6 = Label(self,text='',font=('微软雅黑', 18),fg='red',height=2)
        label6.grid(row=3,column=4)
        label7 = Label(self,text='',font=('微软雅黑', 12),height=2)
        label7.grid(row=3,column=4)
        
        
        self.entry1 = Entry(self,textvariable=self.search_text1,font=('微软雅黑', 12))
        self.entry1.grid(row=1,column=2)
        self.entry1 = Entry(self,textvariable=self.path,state="readonly",font=('微软雅黑', 12))
        self.entry1.grid(row=2,column=2)
        self.entry1 = Entry(self,textvariable=self.search_text3,font=('微软雅黑', 12))
        self.entry1.grid(row=3,column=2)
        
        self.button1 = Button(self,text='2获取信息',font=('微软雅黑', 12),command=self.getEntry)
        self.button1.grid(row=1,column=3)
        self.button2 = Button(self,text='路径选择',font=('微软雅黑', 12),command=self.selectPath)
        self.button2.grid(row=2,column=3)
        self.button1 = Button(self,text='确认名字',font=('微软雅黑', 12),command=self.v_name)
        self.button1.grid(row=3,column=3)
        self.b_down = Button(self,text='4下载',command=self.dwon)
        self.b_down.grid(row=4,column=1)
        self.QUIT = Button(self,text='QUIT',font=('微软雅黑', 22),fg='red',command=self.quit)
        self.QUIT.grid(row=4,column=2)
        
       
# from tkinter import *
# from tkinter.filedialog import askdirectory
# import os


# def selectPath():
#     path_ = askdirectory() #使用askdirectory()方法返回文件夹的路径
#     if path_ == "":
#         path.get() #当打开文件路径选择框后点击"取消" 输入框会清空路径，所以使用get()方法再获取一次路径
#     else:
#         path_ = path_.replace("/", "\\")  # 实际在代码中执行的路径为“\“ 所以替换一下
#         path.set(path_)


# def openPath():
#     dir = os.path.dirname(path.get()+"\\")
#     os.system('start ' + dir)
#     #print(dir)

# root = Tk()
# root.title("路径选择和文件位置打开功能演示")
# path = StringVar()
# path.set(os.path.abspath("."))

# Label(root, text="目标路径:").grid(row=0, column=0)
# Entry(root, textvariable=path,state="readonly").grid(row=0, column=1,ipadx=200)


# # e.insert(0,os.path.abspath("."))
# Button(root, text="路径选择", command=selectPath).grid(row=0, column=2)
# Button(root, text="打开文件位置", command=openPath).grid(row=0, column=3)
# root.mainloop()

