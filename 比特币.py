from bip_utils import Bip39MnemonicGenerator, Bip39SeedGenerator, Bip44Changes, Bip84, Bip84Coins
from bip_utils import Bip39WordsNum
from bip_utils import WifEncoder

# 1) 生成 12 词 BIP39 助记词
mnemonic = Bip39MnemonicGenerator().FromWordsNumber(Bip39WordsNum.WORDS_NUM_12)

# 2) 从助记词生成种子（BIP39 seed）
seed_bytes = Bip39SeedGenerator(mnemonic).Generate()

# 3) 使用 BIP84（P2WPKH，native SegWit）从种子创建上下文（主网）
bip84_ctx = Bip84.FromSeed(seed_bytes, Bip84Coins.BITCOIN)

# 4) 获取账户 0（路径 m/84'/0'/0'）
acct = bip84_ctx.Purpose().Coin().Account(0)

# 5) 导出该账户的扩展私钥（xprv）和扩展公钥（xpub）
ext_priv = acct.PrivateKey().ToExtended()
ext_pub = acct.PublicKey().ToExtended()

# 6) 派生第一个外部接收地址（路径 m/84'/0'/0'/0/0）并获取私钥和公钥
derived_priv = acct.Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PrivateKey().Raw().ToBytes()
derived_pub = acct.Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().RawCompressed().ToHex()

# 7) 将私钥编码为 WIF（压缩公钥格式）。WIF 通常用于传统比特币地址，这里仅作输出方便
wif_priv = WifEncoder.Encode(b'\x80' + derived_priv, compr_pub_key=True)

# 8) 获取 P2WPKH bech32 地址（例如 bc1...）
address = acct.Change(Bip44Changes.CHAIN_EXT).AddressIndex(0).PublicKey().ToAddress()

# 输出所有结果
print("Mnemonic:", mnemonic)
print("Seed (hex):", seed_bytes.hex())
print("Account xprv:", ext_priv)
print("Account xpub:", ext_pub)
print("Derived private key (WIF):", wif_priv)
print("Derived public key (compressed hex):", derived_pub)
print("P2WPKH address (bech32):", address)
