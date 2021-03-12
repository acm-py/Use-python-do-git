import argparse
import collections
import configparser
import hashlib
import os
import sys
import zlib

argparser = argparse.ArgumentParser(description="The stupid content tracker")
argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True 


def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)

    if args.command == "add":
        cmd_add(args)
    elif args.command == "cat-file":
        cmd_cat_file(args)
    elif args.command == "checkout":
        cmd_checkout(args)
    elif args.command == "commit":
        cmd_commit(args)
    elif args.command == "hash-object":
        cmd_hash_object(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "is-tree":
        cmd_is_tree(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "rebase":
        cmd_rebase(args)
    elif args.command == "rev-parse":
        cmd_rev_parse(args)
    elif args.command == "rm":
        cmd_rm(args)
    elif args.command == "show-ref":
        cmd_show_ref(args)
    elif args.command == "tag":
        cmd_tag(args)
    
class GitRepository(object):
    """一个git仓库"""

    worktree = None # 工作树
    gitdir = None # .git 目录
    conf = None # 配置文件（里面就是一个INI）

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("{}位置没有git仓库".format(path))
        
        # 将配置文件读入 conf属性
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("配置文件丢失")

        if not force:
            vers = int(self.conf.get("core", "repositoryformatversion")) # 版本号
            if vers != 0:
                raise Exception("不支持的仓库版本号{}".format(vers))

    
# 处理路径（缺少目录结构时需创建）

# 路径创建
def repo_path(repo, *path):
    """在仓库的gitdir目录下计算路径"""
    return os.path.join(repo.gitdir, *path)

# 创建路径
def repo_file(repo, *path, mkdir=False):
    """与repo_path相似，但是在目录不存在时候，创建目录名"""
    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)

def repo_dir(repo, *path, mkdir=False):
    """"
    如果没有path 就创建一个目录
    路径为空 return None
    """

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception("{}路径不是一个目录".format(path))
        
    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None

def repo_create(path):
    """在给定路径下创建git仓库"""
    
    repo = GitRepository(path, True)
    
    # 和 上面的一样的逻辑,不过条件相反 因为这里是要创建一个原本不存在（给git工作使用的）的目录
    # 确保路径不存在 或者 为空。且需要路径是一个目录，不能是文件
    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception("{}不是一个目录!".format(repo.worktree))
        if os.listdir(repo.worktree):
            raise Exception("{}不是空目录!".format(repo.worktree))
    else:
        os.makedirs(repo.worktree)
    
    assert(repo_dir(repo, "branches", mkdir=True))
    assert(repo_dir(repo, "objects", mkdir=True))
    assert(repo_dir(repo, "refs", "tags", mkdir=True))
    assert(repo_dir(repo, "refs", "heads", mkdir=True))

    # 创建.git/description文件
    with open(repo_file(repo, "description"), "w") as f:
        f.write("未命名的仓库;编辑该description文件来命名这个仓库\n")

    # 创建.git/HEAD文件 （版本号）
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/master\n")
    
    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    ret = configparser.ConfigParser()

    # 核心
    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

# 命令参数处理器
argsp = argsubparsers.add_parser("init", help = "初始化一个新的空仓库")

argsp.add_argument("path",
                    metavar="directory",
                    nargs = "?",
                    default = ".",
                    help = "在哪里(PATH)创建这个仓库"

)

# init初始化功能
def cmd_init(args):
    repo_create(args.path)

# 由于几乎所有的git命令（除了git init）都需要在git 仓库下进行。
def repo_find(path = ".", required = True):
    # 返回一个规范的路径 （例如 会去除中间的空格 或者../../这样的形式）
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)
    
    # 如果当前目录没有.git文件夹 向上查询
    parent = os.path.realpath(os.path.join,"..")

    if parent == path:
        # 递归调用
        # os.path.join("/", "..") == "/":
        # if parent == path then path is root  终止条件
        if required:
            raise Exception("git目录不存在")
        else:
            return None

    return repo_find(parent, required)

# 底层的git hash-object  与 git cat file 实现 
# hash-object 用来将已经存在的文件转换成一个 git 对象，cat-file 将已经存在的的Git对象打印到标准输出
# Git 是一个内容寻址的文件系统。如果一个文件里的一个字节发生了改变，它在git的名称也会发生改变，git不直接修改它，而是在其他位置创建一个新文件。
# 而这个新文件的路径由它的内容决定
# 该路径是通过对文件内容采用SHA-1 hash 算法的结果产生的（结果是一个40位的16进制字符串）。其中前两位作为目录名(00-ff 255个作为目录)，剩下的作为文件名
# Git中 存在着 blob, commit, tag或者tree 对象类型的flag,需要清楚它们的存储格式。 




# 通用对象类-> 单例设计模式
class GitObject(object):
    repo = None

    def __init__(self, repo, data=None):
        self.repo = repo

        if data != None:
            self.deserialize(data)

    # 序列化
    def serialize(self):
        """这个函数必须由基类实现"""

        raise Exception("没有实现")
    # 反序列化
    def deserialize(self,data):
        
        raise Exception("没有实现")

# 读取对象
# 1. 获取hash值 -> 2. 根据hash值计算出路径（前两位目录，剩下的是文件名） -> 3. 在git的工作目录下object目录下查找它
# 4. 将该文件读取成二进制文件，并解压缩 -> 从解压缩的数据中获得对象类型（flag）和大小。
# 5. 根据类型确定实际类。将大小转换成python整数，然后检查是否匹配。
# e.g.  计算出的hash是e673d1b7eaa0aa01b5bc2442d570a765bdaae751 -> .git/objects/e6/73d1b7eaa0aa01b5bc2442d570a765bdaae751
def object_read(repo, sha):
    """从Git仓库中rep中读取对象，返回GitObject（确定类型取决于这个对象）"""

    # 路径获得
    path = repo_file(repo, "objects", sha[:2],sha[2:])

    with open(path, "rb") as f:
        raw = zlib.deccompress(f.read())

        # 读取对象类型
        x = raw.find(b' ') 
        fmt = raw[:x] # 读取对象类型 flag(commit or tag等)

        # 读取并校验对象大小
        y = raw.find(b'\x00' ,x)   # '\x00' 代表着null 字节,代表着终止符.
        size = int(raw[x:y]).decode("ascii") # 读取大小 从空格开始到终止符结束就是文件的大小[本来应该是空格处索引+1,但是切片正好是左闭又开.结果是一样的.]
        if size != len(raw)-y-1:
            raise Exception("文件校验失败")
        
        if fmt == b'coomit':
            c = GitCommit
        elif fmt == b'blob':
            c = GitBlob
        elif fmt == b'tag':
            c = GitTag
        elif fmt == b'tree':
            c = GitTree
        else:
            raise Exception("{}是未知的类型{}".format(fmt.decode("ascii"), sha))

        # 调用构造函数并返回对象
        return c(repo, raw[y+1:])

# 
def object_find(repo, name, fmt=None, follow=True):
    return name

# 写入对象.(和读取对象的操作相反)
# 1. 计算出hash -> 2. 根据hash 得到flag和大小 -> 3. zlib压缩所有内容 -> 4. 将结果写入
# 警告:只有将flag 和大小合并起来才能购计算处hash(读取操作将他们分开了,需要复原还能得到准确的hash)

def object_writer(obj, actually_write=True):
    # 序列化对象
    data = obj.serialize()
    # 复原 flag和size e.g. 
    result = obj.fmt+ b' '+ str(len(data)).encode() + b'\x00' + data
    # 计算出hash
    sha = hashlib.sha1(result).hexdigest()

    if actually_write:
        # 根据hash 计算出路径
        path = repo(obj.repo, "objects", sha[0:2], sha[2:], mkdir=actually_write)

        with open(path, 'wb') as f:
            # 压缩并写入
            f.write(zlib.compress(result))
        
    return sha


# blob类型 - 仅存储一个文件的内容，包括文件名等其他信息。
# 然后将这些信息经过SHA1哈希算法得到对应的哈希值作为这个object在Git仓库中的唯一身份证。
class GitBlob(GitObject):
    fmt = b'blob'

    # 重载序列化方法
    def serialize(self):
        return self.blobdata
    
    # 重载反序列化方法
    def deserialize(self, data):
        self.blobdata = data


# git cat-file type object 命令

# 参数解析器
argsp = argsubparsers.add_parser("cat-file", help = "查看这个仓库对象的内容")

argsp.add_argument("type", 
                    metavar="type",
                    choices=["blob", "commit", "tag", "tree"],
                    help = "该类型的说明" )

argsp.add_argument("object",
                  metavar = "object",
                  help = "要显示的对象")

def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.objeect, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = obj_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

# git hash-object [-W] [-t TYPE] file 命令
# 和cat-file 相反。 读取文件，将hash计算为object。存储到GitRepository
argsp = argsubparsers.add_parser('hash-object', 
                                help = "计算出对象ID并可选的创建blob对象")

argsp.add_argument('-t',
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default="blob",
                   help="类型说明"
)

argsp.add_argument('-w',
                   dest="type",
                   action = "store_true",
                   help="将对象写入数据库")

argsp.add_argument("path",
                   help="Read object from <file>")


def cmd_hash_object(args):
    if agrs.write:
        repo = GitRepository(".")
    else:
        repo = None
    
    with open(args.path, "rb") as f:
        sha = object_hash(f, args.type.encode(), repo)
        print(sha)

def object_hash(f, fmt, repo=None):
    data = f.read()
    
    if fmt==b'commit':
        obj = GitCommit(repo, data)
    elif fmt==b'tag':
        obj = GitTag(repo, data)
    elif fmt==b'tree':
        obj = GitTree(repo, data)
    elif fmt==b'blob':
        obj = GitBlob(repo, data)
    else:
        raise Exception("未知的类型{}".format(fmt))
    
    return object_writer(obj, repo)


# 解析 cmmits
# 格式是邮件消息的简化版本，它以一系列键值对开始，以空格作为键/值分隔符，最后以提交消息结束。
# 下面是例子

# tree 29ff16c9c14e2652b22f8b78bb08a5a07930c147
# parent 206941306e8a8af65b66eaaaea388a7ae24d49a0
# author Thibault Polge <thibault@thb.lt> 1527025023 +0200
# committer Thibault Polge <thibault@thb.lt> 1527025044 +0200
# gpgsig -----BEGIN PGP SIGNATURE-----

# Create first draft

# 值得注意的是，如果消息有多行，会分行显示，行头有个空格(如上面的例子所示)
# 如果将函数命名为commit_parse 会引起混淆 因为commit 和commit_parse 是两种类型

def kvlm_parse(raw, start=0, dct=None):
    """
    Key-Value List with Message
    dct 中就像这样
    {
        'tree':'29ff16c9c14e2652b22f8b78bb08a5a07930c147',
        'parent':'206941306e8a8af65b66eaaaea388a7ae24d49a0',
        'author':'Thibault Polge <thibault@thb.lt> 1527025023 +0200',
        'committer':'Thibault Polge <thibault@thb.lt> 1527025044 +0200'
    }

    """
    if not dct:
        dct = collections.OrderedDict()
        # 你不能在参数声明中将dct 声明为OrderedDict。
        # 这样每次调用都会生成一个一样的dict
    
    spc = raw.find(b' ', start)
    nl = raw.find(b'\n', start)

    # 如果空格出现在换行符之前，则有一个关键字（上面例子中的tree commit 等均是空格在换行符之前）

    # 基底
    # 如果换行符首先出现（或者没有空格，这种情况返回-1）
    # 空行代表着剩下的部分就是消息
    if (spc < 0) or (nl < spc):
        assert(nl == start)
        dct[b''] = raw[start+1:]
        return dct
    
    # 递归的情况
    # 我们读取的这个键值对 
    key = raw[start:spc]
    
    # 继续递归
    # 查找值的结尾，从有空格的行开始，直到我们找到一个"\n"没有跟空格为止 (整个消息段)
    end = start
    while True:
        end = raw.find(b'\n', end+1)
        if raw[end+1] != ord(' '): break

    # 获取消息
    # 在连续行的行头删除掉空格
    value = raw[spc+1:end].replace(b'\n', b'\n')

    # 不要重写已经存在的数据
    if key in dct:
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [ dct[key], value]
    else:
        dct[key] = value
    
    return kvlm_parse(raw, start=end+1, dct=dct)

# 考虑到cat-file 命令，我们还需要还原对象来打印输出到屏幕
def kvlm_serialize(kvlm):
    ret = b''

    # 输出字段
    for i in kvlm.keys():
        # 跳过消息本身
        if k == b'':continue
        val = kvlm[k]
        # 添加到列表
        if type(val) != list:
            val = [val]
        for v in val:
            ret += k + b' ' + (v.repalce(b'\n')) + b'\n'
    
    # 添加消息
    ret += b'\n' + kvlm[b'']


# Commit 对象
class GitCommit(GitObject):
    fmt = b'commit'

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        return kvlm_serialize(self.kvlm)
    

# 日志命令
# git log

argsp = argsubparsers.add_parser("log",
                                 help="显示给定提交的历史记录",)
argsp.add_argument("commit",
                    default="HEAD",
                    nargs="?",
                    help="开始提交")

def cmd_log(args):
    repo = repo_find()

    print("digraph wyaglog{")
    log_graphviz(repo, object_find(repo, args.commit),set())
    print("}")

def log_graphviz(repo, sha, seen):

    if sha in seen:
        return 

    seen.add(sha)

    commit = object_read(repo, sha)
    assert (commit.fmt == b'coomit')

    if not b'parent' in commit.kvlm.keys():
        # 基底条件
        return 
    
    parents = coomit.kvlm[b'parent']
    
    if type(parents) != list:
        parents = [parents]

    for p in parents:
        p = p.decode('ascii')
        print("c_{0} -> c_{1};".format(sha, p))
        log_graphviz(repo, p, seen)


# commit 分析
# 每个commit的id都是根据提交整个对象计算出来的。这意味着commit是不可变的对象
# 如果更改了内容或者author 或者 parent 实际上是新创建了一个对象
#

# 什么是树

# Mode	SHA-1	Path
# 100644	894a44cc066a027465cd26d634948d56d13af9af	.gitignore
# 100644	94a9ed024d3859793618152ea559a168bbcbb5e2	LICENSE
# 100644	bab489c4f4600a38ce6dbfd652b90383a4aa3e45	README.md
# 100644	6d208e47659a2a10f5f8640e0155d9276a2130a9	src
# 040000	e7445b03aea61ec801b20d6ab62f076208b7d097	tests
# 040000	d5ec863f17f3a2e92aa8f6b66ac18f7b09fd1b38	main.c

# 如上所示
# Mode最多是6个字节的asccii 编码

# [mode] space [path] 0x00 [sha-1]

# 解析树
class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha
    
def tree_parse_one(self, start=0):
    # 找到mode后的空格
    x = raw.find(b' ',start)
    assert(x-start == 5 or x-start == 6)

    # 读取mode
    mode = raw[start:x]

    # 找到后面的那个null值
    y = raw.find(b'\x00', x)
    # 读取 Path
    path = raw[x+1:y]

    # 读取sha 并转成16进制字符串 sha-1 结构形式是大端序列
    # sha = hex(
    #     int.from_bytes(
    #         raw[y+1:y+21], "big"))[2:] # big 代表着的大端
    #         # 这里从2开始切片的原因是因为
    #         # 默认16进制前面会加0x 我们并不需要这个
    #  return y+21,GitTreeLeaf(mode, path, sha)   
    sha = hex(
        int.from_bytes(
            raw[y+1:y+21], "big"))[2:] # hex() adds 0x in front,
                                        # we don't want that.
    return y+21, GitTreeLeaf(mode, path, sha)

def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)
    
    return ret

def tree_serialize(obj):
    
    ret = b''
    for i in obj.items():
        ret += b' '
        ret += i.path
        ret += b'\x00'
        sha = int(i.sha, 16)# 以16进制解析

        ret += sha.to_bytes(20, byteorder="big")
    return ret

class GitTree(GitObject):
    fmt = b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)
    
    def serialize(self):
        return tree_serialize(self)

argsp = argsubparsers.add_parser("ls-tree")
argsp.add_argument("object",help="显示这个对象")

def cmd_ls_tree(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.object, fmt=b"tree"))

    for item in obj.items():
        print("{0} {1} {2}\t{3}".format(
            "0"*(6-len(item.mode)) + item.mode.decode("ascii"),
            # Git的文件树显示所指向对象的类型。
            object_read(repo, item.sha).fmt.decode("ascii"),
            item.sha,
            item.path.decode("ascii")))
        

# The checkout command
# 这个命令我们与git有些区别，需要两个参数
# 一个commit，一个文件夹(git只需要一个commit)
# 特殊情况，当且仅当这个文件夹为空的时候,它将实例化目录中的树

argsp = argsubparsers.add_parser("checkout",
                                help="获得一个commit的签名")

argsp.add_argument("commit",
                    help="The commit or tree to checkout")

argsp.add_argument("path",
                    help="这个目录为空")

def cmd_checkout(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.commit))

    # 如果这个对象是commit类型,我们获得它的树对象
    if obj.fmt == b'cocmmit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))

    # 检查目录是否是空目录
    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception("{0}该路径不是文件夹".format(args.path))
        if os.listdir(args.path):
            raise Exception("{0}该目录不为空".format(args.path))
    else:
        os.makedirs(args.path)
    
    tree_checkout(repo, obj, os.path.replace(args.path).encode())

# 实际的功能
def tree_checkout(repo, obj, path):
    for item in tree.items:
        obj == object_read(repo, item.sha)
        dest = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dest)
            tree_checkout(repo, obj, dest)
        elif obj.fmt == b'blob':
            with open(dest, 'wb') as f:
                f.write(obj.blobdata)

# Refs,tag and branches
# ref 是指向git对象的指针, 每个commit对象都有唯一的key,这个唯一的key保存在某个文件里.
# 利用这个文件的文件名来引用相应的commit对象,这样不需要记住那些复杂的hash值. -> 这就是ref的作用
# 如果一个commit对象又进行了修改,会让一个ref中包括另一个ref


# git show-ref

def ref_resolve(repo,ref):
    with open(repo_file(repo, ref), 'r') as f:
        data = f.read()[:-1]
        # 去掉最后的换行符
    if data.startwith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data 

def ref_list(repo, path=None):
    if not path:
        path = repo_dir(repo, "refs")
    ret = collections.OrderedDict()
    # git所展示的ref是有序的,所以这里我们用OrderDice
    for f in sort(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list[f]
        else:
            ret[f] = ref_resolve(repo, can)
    
    return ret

# 参数
argsp = argsubparsers.add_parser("show-ref", help="列出引用")

def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")

 
# show_ref 应该输出
# 832e76a9899f560a90ffd62ae2ce83bbeff58f54 refs/heads/master
def show_ref(repo, refs, with_hash=True,prefix=""):
    for k, v in refs.item():
        if type(v) == str:
            print("{0}{1}{2}".format(
                v + " " if with_hash else "", 
                prefix + "/" if prefix else "",
                k
            ))
        else:
            show_ref(repo, v, with_hash=True, prefix="{0}{1}{2}".format(
                frefix,
                "/" if prefix else "",
                k
            ))


# git tag
# git tag 用来给一个comit 对象起一个别名 之后可以用这个别名引用它

class GitTag(GitCommit):
    fmt = b'tag'


# git tag                  
# git tag NAME [OBJECT]   
# git tag -a NAME [OBJECT]

argsp = argsubparsers.add_parser("tag", help="列出并创建一个tag")

argsp.add_argument("-a",
                    action="store_true",
                    dest="创建一个tag对象",
                    help="是否创建一个tag对象")

argsp.add_argument("name",
                    nargs="?",
                    help="这个新tag的名字")

argsp.add_argument("objcet",
                    default="HEAD",
                    nargs="?",
                    help="这个新tag该指向的对象")

def cmd_tag(args):
    repo = repo_find()

    if args.name:
        tag_create(args.name,
                    agrs.objects,
                    type="object" if args.create_tag_object else "ref")
    else:
        refs= ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)
    

# 
def object_resolve(repo, name):
    """将名称解析为仓库中的hash对象

    This function is aware of:

    - the HEAD literal
    - short and long hashes
    - tags
    - branches
    - remote branches"""
    candidates = list()
    hashRE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
    smallHashRE = re.compile(r"^[0-9A-Fa-f]{1,16}$")

    # 空字符串
    if not name.strip():
        return None
    
    # 
    if name == "HEAD":
        return [ ref_resolve(repo, "HEAD") ]
    
    if hashRE.math(name):
        if len(name) == 40:
            # 这是完整的hash(hash)
            return [ name.lower() ]
        elif len(name) == 4:
            # 这是短的hash(smallHash)

            name = name.lower()
            prefix = nmae[0:2]
            path = repo_dir(repo, "objects", prefix, mkdir=False)
            if path:
                rem = name[2:]
                for f in os.listdir(path):
                    if f.startwith(rem):
                        candidates.append(prefix + f)
            
    return candidates


def object_find(repo, name, fmt=None, follow=True):
    sha = object_resolve(repo, name)

    if not sha:
        raise Exception("No such reference {0}.".format(name))

    if len(sha) > 1:
        raise Exception("Ambiguous reference {0}: Candidates are:\n - {1}.".format(name,  "\n - ".join(sha)))

    sha = sha[0]

    if not fmt:
        return sha

    while True:
        obj = object_read(repo, sha)

        if obj.fmt == fmt:
            return sha

        if not follow:
            return None

        # Follow tags
        if obj.fmt == b'tag':
            sha = obj.kvlm[b'object'].decode("ascii")
        elif obj.fmt == b'commit' and fmt == b'tree':
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None


argsp = argsubparsers.add_parser(
    "rev-parse",
    help="Parse revision (or other objects )identifiers")

argsp.add_argument("--wyag-type",
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default=None,
                   help="Specify the expected type")

argsp.add_argument("name",
                   help="The name to parse")


def cmd_rev_parse(args):
    if args.type:
        fmt = args.type.encode()

    repo = repo_find()

    print (object_find(repo, args.name, args.type, follow=True))


class GitIndexEntry(object):
    ctime = None
    """The last time a file's metadata changed.  This is a tuple (seconds, nanoseconds)"""

    mtime = None
    """The last time a file's data changed.  This is a tuple (seconds, nanoseconds)"""

    dev = None
    """The ID of device containing this file"""
    ino = None
    """The file's inode number"""
    mode_type = None
    """The object type, either b1000 (regular), b1010 (symlink), b1110 (gitlink). """
    mode_perms = None
    """The object permissions, an integer."""
    uid = None
    """User ID of owner"""
    gid = None
    """Group ID of ownner (according to stat 2.  Isn'th)"""
    size = None
    """Size of this object, in bytes"""
    obj = None
    """The object's hash as a hex string"""
    flag_assume_valid = None
    flag_extended = None
    flag_stage = None
    flag_name_length = None
    """Length of the name if < 0xFFF (yes, three Fs), -1 otherwise"""

    name = None