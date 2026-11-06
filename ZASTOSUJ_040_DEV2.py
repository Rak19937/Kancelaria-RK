"""Source migrator logic embedded into ZASTOSUJ_040_DEV2.py during packaging."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# File payload is compressed solely to keep GitHub uploads to one installer.
import base64 as _base64
import zlib as _zlib
PAYLOAD_B85 = 'c-pNz*>c-Pw!hMG9sooTBst4XQHEW#M8}F{NtdE0i>QkNi6#jV1Tbj8H0k(dYNqBJQuj0Rc5B{Z|JOa|bT>9qvg{eTERnsQt<ToW+Xva)8z&jx6XO|Q_}*)ti7<(sboHRa9t`Q<Wf)H*&O}mVW6qKZ%d;Y%u}PA#%l|$NbIvaM-5*|dSs{2<jv)IE<IAJxy_a3@FTMWd$@v*`+1Fq1590?mE2kbuNfCI0kBcnKSB<HUqL9b=ZW2c;#^Z6eN^=++VK~B0OvHXFW=SrX87B;e$T)nS@hD)Um1^@e3xg@QoMAkSFZ@-M_(6yDUmTqtKV&;B^Wz{{FyTkJdGMVDC2<muxq0vqKX-eVyAQwpZuf_ymuwuSGoI!AO}>}=QwIkVBAsQv;4BnO6ln_32F#E75@+{W3ZwvNmopx-v=B3(<6c@s5&VT(4ZFhzGd_eb(0%L^enG+oz>x!3uVL_<g)xJApi!PfXJIqH2%tDhrh)+*fbKwcmT{3LvETx6Rpg&!fSu<}ioD3U=do~+CRq+Z!tgYiK)R^XM3f)H)DHp}P^ck_4B#F)sh=UbvJI3806NDJUUq*tIRfsE3`tr8INv=Tcu#*B^e&<N;Jaabc7Ar$t4baY;}^%zyput%-yMK#VBvTB``-TkK8`q!fWDH4N67f3mt{$2{>6_9P9Lq#FlO+R`ht)c#sQzO*M1ZRe$G89Rsf?3|2s_NnZ<S=<6qTJlBgR+$&x)E3@$E#fQtmgd6o!}A`lEJW+Z)i!T?jA`4LckOuv(K<d5e}(Fv)pXpVzt{u0oE$#8b$kzrU4d<|36ax(eB*fT7R0+2O;4w|GU^jCG^ghT-cgkfY$hn6d+3Xl!cnB{qD*z`vj7B<8x)fn-KeP~|w$EDgTLNYFsEKt;uNQA)c4Hg((#8@q_<!a$ieMLYsO6GnPha5y0Bz`?!!?zW?;Ubr`jD6tye>wZ`?_iGziNINoQ6byJ&~=$at_D_~t!m%!N3z7Nq}B;jPkl67RIr>-c$$0FF#OG!r#Y*{>y{~6qd6cwJTol<v_#0L`YQHORcpxG$op$RRNJJlBZ)}l43hOSi4tg+ucCQ^lr5(($qDMP$YPY8YJqrjzB1ENchSnQNdb01ZRK3hGNDhMh6IKpj79FFcC5PFw5~vkA|BU@E%pc)eGgH(NCN+c&3y6UZ=k@}D^NB|KMs9`y*WnAZWbU?H!vVu$Nv1!KbDoika8l!kW4c_ovoaizh3yclV;%}%){5PF6Y6-Nk{Peq1Id%PeJoMeEza~bnj7gR{(X!h3p1Hy46soA59Z5VY7uR8#$NHyI?&`%Ld|1^O^hgLmTPr;xC)D329)rsRo<8L*N6R0SGnnI$#WwfSX2<Pj<gIEURL#GLuUEX(MB%ksrorycCmd))ImHa9xjKD>>0>Mwf$v^Rrwmfd=NtxOib$_mF@~&Gc1i64{~<AprCKpUlt3vv64~*smuSpTu-&u7%@sKhV4ba}JhVjzNq_gi}Zlz^ts5bx1Biy|QMx6bLgImS--Ry&W8DhdMP_C)@1ES<TkEBT29<NAb&~?si3D*}2BpfNy84c4<DJt#X7mQ)OwLrG)IgSgQFb7ctrc(phU?RLowY2f6UaP`U4Xvm5Z&4;^+1vx)Wlf3SIyhVOr8X|`T1vp@d;Nk~L80w*s`7%1G;B%J%>o3Ip#WHJHo$VDwA!7Q<riiwc19?51q6|;A0tlc^I?jFdUg?yeY(un7EiKTWWG$dSV(knS<XJhJX*;Wc$vvI9e=T4BX8`7u;xmTa275z^vDe`2r0K0dKy^>}v_6l(1l@k2Ub+rU)_PNcEHp3c?d-MlAYF}X4{kWTgxeNoaM@zoVFh#`(BAxX-3D(Ir36P|O*&6HZ-_w!jf!LxY%XPI?Nh&2&PTUN-GXB>By516YUG|@WgHenkzAK6m@SjN&6iDRq8D~X2g#m;QZ7|T;1qT@8K5&%hJf>g^!WyPa$4N2|DNcG0&fGb8)DZSyO8^tJTLvQol(4!paKOhod==na?SeU-f`9vb@bVPm5KtF_js2L7aNsycuKJ`!*d)Z54^$Tx#q8(Z{)=70Ldp=vW72{9@$z$nBedxd0#)BZca>i<e$P1R*-7v87~Dw1Lr#cn0<PloUiY}y$HEeBqtg4>$O9xjMN3ot^@!5j0vjcA&2}{*lY(IwO=Bg|bHvO?pT#t?`7TbqtCe%dfPlC$rls8wSkE*5CJ3h>QKr=bodU8gK--dOqQio4oZE_1%KJ<b?JV;*sT2tJBb3mpSI6NlGvx%%l;<YVos65Bhe{>oEft?N=z$=Z<>VL))=Z|JM0&qiiPGSV!7lh9Ns1D>x2>C7ZQ9K8MFcJ`tj{=CMEMw3sa_jt-F1VxszR18c<uu^CdMQBgkg(2e4zPD0}dbPE>QE9irx($Jbom`5U7GEWn(Dc11-*Tv8N>0xe?F}aN*hGM|-m6W1|Gtc(jM4er#Zbx(TSBPW^Q<4w?!`TXwS%*q!R@fi?sYxHg;PQ0oTTNaZlT0T!5G$i}m}qD7_QQmHe|k|H(tt&NZ^<Bs5{TFuND4o5J-ED44~@s*3e%&XxLiiZ!bpI9lxT*Kjk`J@9izdg1Ln<lVvh?5`A&ilQi?q$zvhkue)*m8q^ShxcW3*)o^p085m*enbJVwK|HTM}yE6DB<h-r!twaU&|l2=I7BvkgaA|MU3zD<G<*kFDrtPa=OR+$PkO$f8R2q)PUb{V;D?wNk_OIgSo)MIywmpiJTU<v<*=SrUT;KL@gb$pdSWfk^?iUBr1-2wZPq2i~m8rCLv{$TXx|U&Y2b!DMVKZ=;XG$umQ(@TPjCfi{=UAS*ayU$V0#-W`F-6#(6s@{j^nV;Ds&=BN>5riqc2(MC@VuTrI$5{Qc^GBzi9=11CBY5HNf(#j-|9H%Ck7~EIY#@?Q>)4&%gYS;z^gf(e~LGPI{!j|=P5tdO#K^Jb9;Tk#$2@frwi^IvxV#dsGzWKTdjO(iDX-%{5_gk3CF=+bF8$>}@N6Hz46FNzvz_eVqfmyAFG<u1ITf)+CE^C=cdjJcxk(1n{P2Kqtt9b1Bd9nz{4Zo|;$H{A+kxvDd2G)zxiVO61FyY>R!A{T!MG=VLBUp160G4bIW0Kp|)mi!Dr-VnoOu&~L7ix?Mr3JkxWbFuNK;%K52^<)Bg+5dgqeBx$T&!R{E?APPWQD_iBG{&!L0heTQPTltxGI7|!hZv@8~c%sFbv}ibOm5eo}<(t;EPEV$!&tw1P<l|?KY<6ij<+#4$kh_FQ&7caU`z8&Y^G^r<igBe@+M*PtC+e;Ni^$f*NCn9jnp=p$iGC5PX$bgaS)g-~-is<O}GWFrvn4VsM0jF65aK%mK!hQ5f^jbsTR*vNgpnW(7=Lel3bHP$Q?H6TufNvsLgF$NTa8RsXDe>KYCR63GzaM4>2ma2Dk?%FOvCG*AMy>Vvip0Tr{4=q~Qcp9A#*AfFsxk=8_Vfmf4t2o_TI_<{X~T2kwT)Wx#0t+l7%ZH6P1;&u2NV1$5`MvL~0#H~zFs#(1y1SXiC$Y*k1o7g7(MS`I=dA>+pZ0TTN<%wc43E!B81I5~}YwB5ShMgP~7t>f8Hu<uExvP_ExDF;QeTP(bf?|;pn)U>G2^0ZejKk2Sr4BYVK!@a^)$BTPCQ%_~rgfMIXM*H4p$L{(oS1ce4Yk@A0{Co1N~gVW)kJkH5P>2F;hdX`5PV_aTQYaig4N8nl4B1=%acNG22cj0p{Q!w${PKR7{mkZoG<(smVAJG6>ZXM-6dCexw@75Q5xq^FE0oIV~)F33!pYG_=a__!KI|BDzFaa5VAskZtjuDGR*G-oaSa=y>&@o$d7sDh_7LigfdSdXn=JZ^6{E~_`ArLKB?DPmc-$@k#-73ZVkdcLtyeC4(E>eD{dEkUAY{JpjSpPGOlZoX?nR5_*;jlp{ctdq9{P7wRK}*JGM_H8!&gU_Lm{3b+yG1^Bd5YX}0D8W!p#odZkQBi7v?;hox3W+9Z9XrOentMdskIZ%m2{cZ?F1+Avc4LCBP@9-0~>8wbB-EkKPOjJ5{>!RYp7pxk{BWVz!7-cMbc>#NDnz>8|&raCoPpgF1Pu3N-!GjwB!TR7Pk+0SHV#lk7bGAOAinHJ30QDC%`5?S(K8#|LILIk$(vpqz`$UNh`;-wth+CW^AxikSCH9)qY?y|Pkt0o6>RC}WtkG2fG71H)ZWkjAV7Gdtm2|lhNWjikzse(<;De?j>lU(<zi=M6BJN#x#4`>AgwiWCrE5*ZVURhp!R}@nww!!#@xdvjYHruFqmrVY&nrEv#L7@zidGg`!<8>0h|3_1UzW?1}XZ{VS*lbx(@+%{;6mx$qHwl6@gkGQyi&6=tplZ;-zC~5qG4IyDRtf&QMsKG`@sxo1HfW9zR2`(&XzPo23W}DOqTSuM2JLF(Mh6pUh;x}hgJ?^lXLRsffHGD9P7=Mw9NJb1s(uW;u#Aqv!8YoE8J!5=HXD}u-B#Zx80A}4IJtcH)!&<&@C}V#t`3`KyL~-Vwfzw$))F@xK2V9#-6r7vW<YwY<-)8j9<9smEheIFwdVG6wsOn$Y~C9?Z5HO8yS4rr^?b`GAuE8oU#vg;%?CFo&OwQXm{;f1%#Y&a!~c%M4wwRzJ^;|N?z>sC$?K2!l(sCgwV*bHa^uWJV`e=v-*N`yPA~4H$Ib^oo%H(MA2CdR(LForop$>tUC=Z@nIiCMC#SxvI1WMOU`n?@a*jUy?fvhlZd!x|lHI*BYd=KW1`5`WaY#O;uSu_zbbF(yrj|c0$#+rWvJSmZB9SeD0f)>lAjtRg)p)IBMN%Q5ZB^|yK#&EoF1vu*@p=`PU<05VFt^;WkAh!?Bm}gFvYBN?nxnzpj4|71wa#TAuDh?Q-6)*{i1;K|hwrjv%pnXOXTF$$2!KK2`7+7o&3Hpi+6rAOt$bLSN>#aGCvnAU%qx#v@3K72{CU$Bf^Xf9CaOHWOA#h+h6-&{02n{;a0}1eh*7Kf2Rq9opfW(#7w)DBx_?Ln5mD^pR=WTh(nc6$C<*fApMPX)mc9R7%F$X`?aD&eT@r-rN*liG8f9fuACKRG2U^m8Pqp=$G%_}N0?uk4R}Dh@f9j*kb1EZ?yE1Vu?uq@e!dAK=#Z8$SN)u4L%BK$b;<lhrX*)MBQV<16fQF^MuCYy)voBm`8XzN-rdxrl0P=go=lRM@L$NTdPh%V}p{#pQx52wrnJac^O)jx0U65<7(wqL|-HJ;uiHog@hZM1lIzy%@@#h~)kgtZ`EK{ig=&~>tdtp3E-t6Jh=2;`1daP2Bf(|h6$`<Ue1ur<c0@RV6AN3DGT(oiw$9U8>OJ0LEN$~W@6h8Q4O6tio#4<q!D31h-!q?<VsFW*^Jf4a$;Bssa$`-<5UC=Xpft%wqT+3QFag}F<k(i%@&cf6j1QrR4Fg9Ug?8gE~p|bE1ZbQlwfNJ-Ja-9zQ5g}RlfE~0D!&nVZ$BZ+s$PRVjl%uYc1n?)IdTV+Tg}~49|45Qkq6zcgozJAYijfY{%mKNIRw5MDeDHnEy@=-kG4}IL&yQX(x0=Q|O~!N73*JxN7rjPJ?=?t~tUB+%pk4N6wy{j$q4O(G!Q+msUU2Xc0s=lRz{fWX<EY>34ti|ReR|qsC(qc~`GEC)KDiuRDvoRDJrWPI=GsYt2-wNlp!Wj+a?w9|+3o+rUi5xp{ob=)zXuM>WnFO0FtFJ989VNs_F&SZ?&VSUxK|4kWCDHA`*}csoV_|dg~rdiuTBTdAT|dEJ9^$bdSS|@Cug8#R0XLRB`5F&35I%yoED=IjZo2T(-^geevVn1T$DI&G~chamJwLsf#`1^`{-34h%)d7Cog-KgYL@<+1E14z4``s6mL$>j(b11c@qFhiLl5PPZ9$tyM<?xQnqH7Wz^gjsF!_FLhO>I9rUraz*HOX6=avdz@vd=mrc~POHw`SpTFEHJ3l=KktpYIpBT2Ozu1=LOn5$?fh5<@TM%cl_Z{%H1p4IcvezFV!_K!-qnxr1e8st%OZu1Y>8swQ`NXaS%&<3DSnB}vKRQ2qc6xF&D5tU5@i}{Sag2<->?xAD<%l%B3*%N0xEoUdRt-|sb{2qML>|!a?Hy~{5P)(A;x$VB1EHG73@Wlc?fn2N>Ez|h-th@QT94qeWa+j@thj&UlrV*kHl!Yflc6Jbn!L?K;jQ9v!+tzJIjgG+Fq<gS4hTy%S93HeQ#VeNtgL%>%t9(GglniBpjOax-p4aaPk*W5!A?(Jo($LluE&NvwhvMy%X@7bBNiy?Agw0!xia)b;4mFB+A6_=4^-74pmBZ3Bn4$<jhe>wEj%;~C1%@*TNAyylGKaV)gN{aT1lI`<Z^RGlb}kZZEI_)MxAy*xqNnV+Pn0QPx^a?)Mdt=#Ix=hE?wC}#td|#*K7pbdFIoRq(X4HrVC+5empI}nWJe`6Hjj$%fLeu->&YZkiu6~bDKumEa$OWJ8rixF#P$F9f#obWO&vJToc^e<apt!+I~J%n@8yOQsNDFoMj(yaO5Vm(;Rd>1N1;L?&7{&KgjhGa>CnvVkhIwLt??l%`5;`s%0ZvmZW@Qi(-nWz|c?f&^vOUZ1z_Y0fW;TY_C9OG|a31smOcP`4+EB;s0wJmkpg-LvX=>x4644y;yE%3RAOk%Z{dHD<K851M6#?6#9tOzq7KQ+)ta|nR?l}qLeFx+DGwT?lLRarb6cP(_bjY5M6nADUa)prlCR+5QJS)tzfX;j9aPCdn|)CMTZaWr>YcwlB`ecPtrxh2Omj4n>q({)j9YcrL9TDZIo=GCC?eOPFmHBGv3J}%iP(f3BRPf0T5DG*`H*>Y6&C^<ZL!7a-||No^n5D`hY~hWb)@z^wH-qLAxsVp#G+X89t~h%o!+MB2s5#53S+JY!@F;oJGr-pzz39`eANjsF@VG`|w+9Tbpsj{mlHN6>|5QkimC*L2O7&B_o@O{%MqqAQo4FT#Jzu6LwUc+YIq2u=OMarR!JQU)wgYa$Tkzc$8Bw8+_%b=RbSh%U{lpyqD+4J;RpjapTNa&7+iXHC!SciGqzoAoMXiRg5V_AJYmO+m{--D!3icC$*F5(gL#Kvv3Js%O-aTlYqp7UC>L0Ei)1Ad~$7kc|k$*UW$X@jdR_AWwz4d*N!tj&9A=QUq(l^?*1wtw+VC22X4E^;0sr-s*9s-^M%P>esYTkOvR<QEY&M(hZi67e7F0$%}}ijf7BV*w!m&tn_H7$co94V@2_!vKli8PLrv%i+yXyq=T6w*TH(T@6LL~@p&n(X&KS#k^JldqgdncDFXrT;1%XT}fv<+w;N@95{swQdhdI3mP$ttpF|l;ZrHe+I>0>A6J}<wty_ZTJsy-$6>^iHevv()h=T(Yn{J+Ti=z!I2_t(kzflD9eo@WXkO>DNnn>Ew&ZZ3%>tuFVQ{r$RL5Jif&kDao=>RCT%10!n5mVX+WamrO@q#$tRik6=tLcpx(EXfogU)egpu1?r-fC_ZO71Uni*@ibV<fs%uSf2UcymwelLW%P77O^h39zE2$Q5Rk9U+bbR16>_lt4oX<+44IWV*DiL{)d0D>e|<efdJ3T^f+lz)L_D&a8E}<W(_9m5Yy#u4UR)eAGrl0Z=K5$eP6sfD^A6FzhZ;DpMuB$53MG_+P@(L3fd7~Bp?38**XDQz5gfe`Q5z#Jzv#t+~eGcfMx)GwjNj9{1g~2U}AZFcM)>DwHdGjHu7&^^dMmm_u0#*j$wau@U>N)ZMiMHH8)NoNV4dyBTCsWl7PDu_T0->mx)6>>jVCod+SMjAWSvGMxZLuXQW0JJP5%;IHWn1qM%13&^pUA%J`5+P#yPbMH4!Tert$u8vCdgh0(dXwvAd4DGREwe3f#eW1Pe>H{LbJE5k#Gtqv)6-9OZ(ZRyREh~JF4aahKxhEYF8B{q?LfleCkn9$J}X-wo!Y>vASA}>bry$swf8L#w_gIwMROd{dj0^p~nA>`o;6wg~Ic#k{;jxG<o%cDCgOM-&f9{N5ZLXo*2O{tRWvL%jhW&vwiD;u?phsMutCM4`C<FGAW)5(fPE@C4SVUIyDam3Ne+8m_J<F@`;w<IIV12GPLYTY9wiq>xj+V$kcKK)#8Lq#FkPHL1$-8Xe14VcwFhFD8A0t+3m+BrCD;g;iyH6_q;+EfHwPcUk&B7L;&quk=%)jT{k^7iPf5fh(FHM4+#xOumN9vupEfyc1b-3+|gATNFJxB}Iw4|g)5QIrmw_#s|1kvoO5gAGgES93LWnhwix$JN<zgv;qVBq{eh-?HK4mTv2wJmcWu#Y*tU8vgD81WaofR6um-tGfS!{RC-d+8dVl005hd705{pVi%zF(nXpvQk<^F<o<X@6XQL#ym5Ob3SpcT*bYC&E07~>pK*E2Fnf*O4K&3)Svm<tJG4q&@j&e^muNAQJ5xt%Q3uL#H@Jx9{nOWBz!U3pH)zA8aamb?T!$&Dn)3UbMdWZi9_#cXx^*;w&j@mFpyuPiib&pXF5Tg$s6j8NsM#ukKwza?fy3z+5#8FRYEM?n*Q0*+etvn%T=qTtiXH4f{6_teRp+k;7q15RcG$P&^H9=(1$ey$UyNWS$-5!y6%1J>uhG^6QH8JbYnVR6b2?$-5b!7GQd5zZU)Q~Wc#^nlJXnLDOgU~d(8CJ4$l-}_%^xdVwjN!poPX2!74J%Y_}2<duDsuc1kmRm3iOsxOv3f5ar$0jA#bhV#9MEvsOJ>i32g(I3Zk8Z?T=z?fp`<zi)_v3S%T-6@FgsK5`fQvy8axG9zyT-y92#}gOY$RUB%OKuG+r4GVt`bxyhiSjT%EKmY^sBLk%<vc=H<nUzgX!b65A*KDLvody)>`9=_T=xTbr_4&6xBja6>Aeo=!w@wY}2;9bfj5XQSk!XnAtme|>bzQqg`b#B3`$0)#f3l!-jKG>)Z&M7+ixPvUzE58H%VkpJ;c@CWYcSilX1z=_jhq2+@Bw-8=hWs0YDRJ-(AtIesJ}yT34l5A}1eO|^)~(rH($Fv#go1Q4RKmPtq=v0O&Keg=6@zi!t4_5%ukC%?$WbV~N#;)xE!+aG)75p2G|k`CPob3*!b_Z;J@pQuAOQ!WD1GfD*>o?!04<&_qP>Uv``_)MNvIPl#b-6#tLye!`P3Cp&Id#_9KvN#TRbq$&?%*b&J7`*)($Q|I&y8@kvR`BTjorPD5BfuW`-2lljF-j!(p&99FpYN)kJq62cPqm8~KY-;4{&o?b60w^<c-ag{5w`Tb6az`ELKZc?_DSMm!`aZEdwp$f>2()-*tL2b>s?WwR!wAWpcB=+?E299rT?5`i-3x?0NeZBm9~R>RVC)~8DyUo<XZFT~WX*(_5UBDZdpENS9YYyjwAb-w=!EfW2@t~-6RBA$cb;r<8=EYDzG79+g+t}mYBW?ZfI87RhEs*b@iFRNNSL+t6?Iy7GT(R?FAEML#daU@S^B#IM(++VoNptmdOJs3m1``2t5gd$BuNO^k;s8;zs#=W-~Fou>C(NclvwWmU%Y=?xm?gX@?L5YH#<o>cyzIuX<Mttoh!FavO3s0(;LbgPQbK{i@^ey+kY91=bH>;d|`7jErzcho4!k7c^9gqF?OE#1%rdJRg_SN1nHu2@a$LuY_Xh4XAmM;XkIm80IuZ-TBA3dXPE@(6`8B3XQc1G~UlqD9muh-&xA4N<aut|?dV46P6Ejg7QTRtY@mL8}B5l*(c1dn8#qt&NVpWELHxi+jPj$-Fwx!lYz<XbG&!xIYl1`vm3zD0vmAuA6yx(r`Y?W;#7w)E8<@O4eu_*MVZRNWmYwduhhy0Sh41yl7yD0MseriYU!uRvC_BVWj+0&4|XWU$|U!wJ-B9jYh?m1S0i0J|5?jJ<0jpx$p#NIaL{N&xlq8f9<&+ym~&)Se4c@5WT^HejjKQ;lx3x8?NjEZz4Vgf}QardLDmKBy65@8HWj%fvEVOXtVG{&M-E`=f`6xaa-zvy)%DM?dzw{crYF(DvmQdxgmMK$!P<{F<c{hJCGroL5;fp5YmPdgC%p*xFyr<M93O<FH`Ks9-*3I`K5~A-)qS?~~CDo8ZI$>C@kzvG3q#Q_}zU*<QdW9h};e4!YI0oAmaUn-7&wj4n;7)Kgaj;dHYpEl*{x^gTGo4+76ub*7<@Y#TPc7en_AXFN(><App7&W<t3OKI~6NoKPpo9BQ2k*yYNxf1#Nf21K^9rBlc7W&35)9mi5^WugrBWzcmxAO7~PdvyOFOnRuqaqW^YbG4i(ek#9pflgBeZ*hob=_1NU!1f&zND{VY<-`=cgm|9+pc9a{7rP1?sqH0I;?N!s-C}AH^ueA`i^0%iL7Q*lGU4*;Ru1&^8|!dzGzszby!~3MK-nb^S+~~zKP2jh#cL+SO7Q(n8PlT>i$=umQV^cOL<?TWZ`xkx82UEQJ8`_+{dO=rRRaC;CU#zo@aEV2*cuk_y6-O;gk'
def _decode_payload():
    return json.loads(_zlib.decompress(_base64.b85decode(PAYLOAD_B85)).decode('utf-8'))

OLD = 'VERSION = "0.4.0-dev1"'
NEW = 'VERSION = "0.4.0-dev2"'


def replace_once(s, before, after, label):
    n=s.count(before)
    if n!=1:
        raise RuntimeError(f'{label}: oczekiwano jednej kotwicy, znaleziono {n}. Nic nie zmieniono.')
    return s.replace(before,after,1)


def node_info(source, name, cls=None):
    tree=ast.parse(source)
    nodes=tree.body
    if cls:
        matches=[x for x in nodes if isinstance(x,ast.ClassDef) and x.name==cls]
        if len(matches)!=1:raise RuntimeError('Brak jednoznacznej klasy '+cls)
        nodes=matches[0].body
    found=[n for n in nodes if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
    if len(found)!=1:raise RuntimeError('Brak jednoznacznej funkcji '+str(cls)+'.'+name)
    n=found[0]
    begin=min([n.lineno]+[d.lineno for d in n.decorator_list])
    return begin,n.end_lineno


def source_function(source,name,cls=None):
    begin,end=node_info(source,name,cls)
    return ''.join(source.splitlines(keepends=True)[begin-1:end]).rstrip('\n')+'\n'


def change_function(source,name,new_code,cls=None):
    begin,end=node_info(source,name,cls)
    lines=source.splitlines(keepends=True)
    lines[begin-1:end]=[new_code.rstrip('\n')+'\n']
    return ''.join(lines)


def get_base(repo: Path):
    files=['app.py','rk_inbox.py','rk_sync.py','rk_cloud.py','rk_cloud_server.py',
           'rk_domains/documents/ocr.py','assets/service-worker.js',
           'TEST_ARCHITEKTURA_040.py','RAPORT_JAKOSCI_040.py']
    content={}
    for name in files:
        p=repo/name
        if not p.is_file():raise RuntimeError('W repozytorium brak pliku: '+name)
        content[name]=p.read_text(encoding='utf-8')
    return content


def build_changes(repo: Path) -> dict[str,str]:
    src=get_base(repo)
    app=src['app.py']
    if NEW in app:
        required=tuple(_decode_payload().keys())
        if any(not (repo/n).exists() for n in required):
            raise RuntimeError('Wersja dev2 ma niekompletne moduły. Przywróć źródła z backupu przed nową instalacją.')
        return {}
    if app.count(OLD)!=1:
        raise RuntimeError('Aktualizacja wymaga dokładnie wersji RK KANCELARIA 0.4.0-dev1.')
    if 'SCHEMA_VERSION = 330' not in app or 'SCHEMA_VERSION = 240' not in src['rk_sync.py']:
        raise RuntimeError('Źródła schematu SQLite są inne niż w przeanalizowanym RK 0.4.0-dev1.')
    created=_decode_payload()

    # 1) Real further split: move the original ~450-line schema logic unchanged
    # into a dedicated core module and inject its external dependencies explicitly.
    schema_fn=source_function(app,'init_db')
    dependencies=('ensure_smart_schema','ensure_inbox_schema','ensure_document_hub_schema',
                  'ensure_action_center_schema','ensure_correspondence_schema',
                  'ensure_workspace_plus_schema','ensure_case_categories_schema',
                  'ensure_caseflow_schema','reconcile_task_alerts','seed_demo')
    schema_fn=replace_once(schema_fn,'def init_db() -> None:',
        'def initialize_database(db, *, schema_version, '+', '.join(dependencies)+') -> None:',
        'Podział init_db')
    schema_fn=schema_fn.replace('SCHEMA_VERSION','schema_version')
    created['rk_core/schema.py'] = ('"""Schemat SQLite: oryginalna inicjalizacja i migracje, bez importu app.py."""\n'
        'from __future__ import annotations\nimport sqlite3\nimport os\n\n'+schema_fn)
    app=change_function(app,'init_db',
'''def init_db() -> None:
    """Cienka fasada migracji i uruchomienia kolejki OCR."""
    if pending_sync_journal(DATA_DIR):
        raise RuntimeError('Przerwana synchronizacja! Nie otwieraj RK KANCELARIA przed odzyskaniem z kopii Data. Użyj ODZYSKAJ_SYNCHRONIZACJE_040.py.')
    initialize_database(db, schema_version=SCHEMA_VERSION,
        ensure_smart_schema=ensure_smart_schema,
        ensure_inbox_schema=ensure_inbox_schema,
        ensure_document_hub_schema=ensure_document_hub_schema,
        ensure_action_center_schema=ensure_action_center_schema,
        ensure_correspondence_schema=ensure_correspondence_schema,
        ensure_workspace_plus_schema=ensure_workspace_plus_schema,
        ensure_case_categories_schema=ensure_case_categories_schema,
        ensure_caseflow_schema=ensure_caseflow_schema,
        reconcile_task_alerts=reconcile_task_alerts, seed_demo=seed_demo)
    start_worker(sys.modules[__name__])
''')
    app=replace_once(app,'SCHEMA_VERSION = 330','SCHEMA_VERSION = CURRENT_SCHEMA_VERSION','app schema version')
    app=replace_once(app,OLD,NEW,'app version')
    app=replace_once(app,NEW+'\n',NEW+'\nINBOX_ASYNC_MODE = True\n','asynchroniczna kolejka')
    app=replace_once(app,'MAX_POST_BYTES = 256 * 1024 * 1024','MAX_POST_BYTES = 64 * 1024 * 1024','HTTP request body limit')
    app=replace_once(app,'from rk_paths import resolve_runtime_paths, installed_data_dir\n',
'''from rk_paths import resolve_runtime_paths, installed_data_dir
from rk_core.schema import initialize_database
from rk_core.schema_version import SCHEMA_VERSION as CURRENT_SCHEMA_VERSION
from rk_core.sync_atomic import pending_sync_journal
from rk_core.request_security import csrf_for_session, csrf_valid, csrf_html, same_origin_request
from rk_core.cloud_security import validate_cloud_url, CloudCryptoError, encrypt_cloud_snapshot, decrypt_cloud_snapshot
from rk_domains.inbox.worker import start_worker
''','core imports')

    tesseract=source_function(app,'_run_tesseract_on_file')
    tesseract=replace_once(tesseract,'timeout=120','timeout=30','Tesseract per-page timeout')
    app=change_function(app,'_run_tesseract_on_file',tesseract)

    # CSRF: all authenticated POST forms and same-origin fetches use an
    # unguessable token. Setup/login only rely on Origin/Referer as before.
    app=change_function(app,'send_html',
'''    def send_html(self, content: str, status=200):
        token=csrf_for_session(self.cookie_value(SESSION_COOKIE))
        content=csrf_html(content,token)
        data=content.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','private, no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.end_headers();self.wfile.write(data)
''',cls='Handler')
    app=change_function(app,'set_session_cookie',
'''    def set_session_cookie(self, token: str):
        secure='; Secure' if os.getenv('RK_HTTPS_PROXY','0').lower() in ('1','true','yes') else ''
        self.send_header('Set-Cookie',f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_HOURS*3600}"+secure)
''',cls='Handler')
    app=replace_once(app,
        "        if path == \"/system/ws\":\n            return self.websocket_presence((qs.get(\"tab\") or [\"\"])[0])",
        "        if path == \"/system/ws\":\n            if not self.require_auth(): return\n            return self.websocket_presence((qs.get(\"tab\") or [\"\"])[0])",
        'auth WebSocket')
    app=replace_once(app,
        '        u = urlparse(self.path); path = u.path\n        try:\n            fields, files = self.read_post()',
'''        u = urlparse(self.path); path = u.path
        # Deny unauthenticated large uploads BEFORE loading request bodies.
        if path not in ('/setup','/login','/system/closing','/desktop/quit'):
            if not self.require_auth(): return
        try:
            fields, files = self.read_post()''',
        'early auth')
    app=replace_once(app,
        '''        if path == "/system/closing":
            client_closing((parse_qs(u.query).get("tab") or [""])[0]); return self.send_no_content()''',
'''        if not same_origin_request(self.headers):
            return self.send_html(auth_layout('Odrzucone żądanie','<div class="error">Niedozwolone pochodzenie żądania.</div>'),403)
        if path not in ('/setup','/login','/system/closing','/desktop/quit'):
            if not csrf_valid(self.cookie_value(SESSION_COOKIE),fields,self.headers):
                return self.send_html(auth_layout('Odrzucone żądanie','<div class="error">Nieprawidłowy token formularza. Odśwież stronę i spróbuj ponownie.</div>'),403)
        if path == "/system/closing":
            client_closing((parse_qs(u.query).get("tab") or [""])[0]); return self.send_no_content()''',
        'CSRF route preflight')
    app=replace_once(app,
        '            if path == "/inbox/upload": return self.inbox_upload(fields, files)',
'''            if path == "/inbox/upload": return self.inbox_upload(fields, files)
            if re.fullmatch(r"/inbox/\\d+/retry",path): return self.inbox_retry(int(path.split('/')[2]),fields)''',
        'inbox retry POST')

    # Confirmed authorization gaps: raw database backup, permanent purge and
    # unlocking/deleting closed cases must never be available to standard users.
    for method,signature in (
        ('backup','def backup(self):'),
        ('trash_purge','def trash_purge(self,trash_id,f):'),
        ('case_unlock','def case_unlock(self,cid,f):'),
        ('case_lock','def case_lock(self,cid,f):'),
        ('case_delete','def case_delete(self,cid,f):'),
    ):
        old_method=source_function(app,method,'Handler')
        hardened=replace_once(old_method,'    '+signature+'\n',
            '    '+signature+'\n        if not self.require_admin(): return\n',
            'role '+method)
        app=change_function(app,method,hardened,'Handler')

    # Cloud: no transmission over remote HTTP and encrypted-at-rest envelope.
    app=replace_once(app,
        "        if url and not re.match(r'^https?://',url,re.I): return self.cloud_page('Adres Cloud musi zaczynać się od http:// lub https://.')",
'''        if url:
            try:validate_cloud_url(url)
            except CloudCryptoError as exc:return self.cloud_page(str(exc))''',
        'Cloud config HTTPS')
    app=replace_once(app,
        "<button class='btn primary'>Wyślij do Cloud</button>",
        "<label>Hasło szyfrowania Cloud (minimum 12 znaków; nie jest zapisywane)</label><input type='password' name='cloud_passphrase' minlength='12' required autocomplete='off'><button class='btn primary'>Wyślij do Cloud</button>",
        'Cloud passphrase push field')
    app=replace_once(app,
        "<button class='btn'>Pobierz z Cloud</button>",
        "<label>Hasło odszyfrowania Cloud</label><input type='password' name='cloud_passphrase' minlength='12' required autocomplete='off'><button class='btn'>Pobierz z Cloud</button>",
        'Cloud passphrase pull field')
    app=change_function(app,'cloud_push',
'''    def cloud_push(self,f):
        if not self.require_admin():return
        if not LOCAL_MODE and os.getenv('RK_HTTPS_PROXY','0').lower() not in ('1','true','yes'):
            return self.cloud_page('Cloud wymaga bezpiecznego HTTPS dla dostępu przez LAN.')
        passphrase=str(f.get('cloud_passphrase') or '')
        if len(passphrase)<12:return self.cloud_page('Podaj hasło szyfrowania Cloud (minimum 12 znaków).')
        with db() as con:cfg=cloud_config(con)
        try:
            from rk_cloud import get_meta,push_snapshot
            validate_cloud_url(cfg['url'])
            remote=get_meta(cfg['url'],cfg['office_id'],cfg['token'])
            remembered=int(cfg['last_version'] or 0)
            if remote.version!=remembered:
                return self.cloud_page(f'Konflikt Cloud: serwer ma v{remote.version}, a komputer v{remembered}. Nie wysłano danych.')
            raw,name=create_data_snapshot_zip()
            encrypted=encrypt_cloud_snapshot(raw,passphrase)
            result=push_snapshot(cfg['url'],cfg['office_id'],cfg['token'],encrypted,remote.version)
            with db() as con:
                settings_set(con,'cloud_last_version',str(result.version))
                settings_set(con,'cloud_last_sync',datetime.now().isoformat(timespec='seconds'))
                settings_set(con,'cloud_last_sha256',result.sha256)
                immutable_audit(con,None,'cloud',None,'Wysłano zaszyfrowany snapshot Cloud',
                    f'{name}; wersja {result.version}; SHA-256 {result.sha256}',self.current_author(f))
            return self.cloud_page(f'Zaszyfrowany snapshot przesłano do Cloud (v{result.version}). Zapamiętaj hasło!')
        except Exception as exc:return self.cloud_page('Nie wysłano danych: '+str(exc))
''',cls='Handler')
    app=change_function(app,'cloud_pull',
'''    def cloud_pull(self,f):
        if not self.require_admin():return
        if not LOCAL_MODE and os.getenv('RK_HTTPS_PROXY','0').lower() not in ('1','true','yes'):
            return self.cloud_page('Cloud wymaga bezpiecznego HTTPS dla dostępu przez LAN.')
        passphrase=str(f.get('cloud_passphrase') or '')
        if len(passphrase)<12:return self.cloud_page('Podaj hasło odszyfrowania Cloud.')
        with db() as con:cfg=cloud_config(con)
        try:
            from rk_cloud import pull_snapshot
            validate_cloud_url(cfg['url'])
            raw,meta=pull_snapshot(cfg['url'],cfg['office_id'],cfg['token'])
            plaintext=decrypt_cloud_snapshot(raw,passphrase) # authenticate before any DB modification
            create_shutdown_backup(retention=30)
            ok,msg=schedule_data_snapshot_restore(plaintext,f"Cloud {cfg['office_id']}",meta.version)
            if ok:
                with db() as con:immutable_audit(con,None,'cloud',None,
                    'Zaplanowano przywrócenie zaszyfrowanego Cloud',f'Wersja: {meta.version}',self.current_author(f))
            return self.cloud_page(msg)
        except Exception as exc:return self.cloud_page('Nie pobrano danych: '+str(exc))
''',cls='Handler')
    app=replace_once(app,
        'def main():\n    apply_pending_restore_if_any()',
        "def main():\n    if pending_sync_journal(DATA_DIR):\n        raise RuntimeError('Przerwana synchronizacja. Najpierw odzyskaj dane z kopii; nie uruchamiaj programu.')\n    apply_pending_restore_if_any()",
        'fail-closed sync startup')
    src['app.py']=app

    # ZIP bomb limits before reading data from a potentially untrusted Cloud snapshot.
    snapshot=source_function(app,'schedule_data_snapshot_restore')
    snapshot=replace_once(snapshot,
        "        z=zipfile.ZipFile(io.BytesIO(raw),'r')",
        "        if len(raw)>512*1024*1024: return False,'Archiwum snapshotu przekracza limit 512 MB.'\n"
        "        z=zipfile.ZipFile(io.BytesIO(raw),'r')\n"
        "        if z.getinfo('sprawnik.sqlite3').file_size>1024*1024*1024:\n"
        "            return False,'Baza w snapshot przekracza limit 1 GB.'",
        'ZIP expanded DB limit')
    snapshot=replace_once(snapshot,
        "            parts=[x for x in Path(rel).parts if x not in {'','.','..'}]",
        "            if any(x in ('..','') for x in Path(rel).parts):\n"
        "                raise ValueError('Niedozwolona ścieżka w snapshot.')\n"
        "            if info.file_size>256*1024*1024:\n"
        "                raise ValueError('Za duży pojedynczy załącznik w snapshot.')\n"
        "            parts=[x for x in Path(rel).parts if x not in {'','.','..'}]",
        'ZIP member safety')
    app=change_function(app,'schedule_data_snapshot_restore',snapshot)
    src['app.py']=app

    # Inbox: queued+recoverable OCR, no decision before review.
    inbox=src['rk_inbox.py']
    fn=source_function(inbox,'ensure_inbox_schema')
    fn=fn.rstrip('\n')+'\n    ensure_async_schema(con)\n'
    inbox=change_function(inbox,'ensure_inbox_schema',fn)
    inbox=replace_once(inbox,
        'from rk_domains.inbox.service import stage_inbox_upload, InboxUploadValidationError\n',
'''from rk_domains.inbox.service import stage_inbox_upload, InboxUploadValidationError
from rk_domains.inbox.worker import ensure_async_schema,job_state,retry_job
''', 'inbox worker imports')
    inbox=replace_once(inbox,
        '            cases = con.execute("SELECT id,signature,internal_signature,title FROM cases ORDER BY status=\'closed\',title").fetchall()',
        '            cases = con.execute("SELECT id,signature,internal_signature,title FROM cases ORDER BY status=\'closed\',title").fetchall()\n            job = job_state(con,item_id)',
        'inbox review job lookup')
    review=source_function(inbox,'inbox_review','InboxMixin')
    review=replace_once(review,
        '        if row[\'status\'] != \'pending\':',
'''        if job and job['state'] in ('queued','processing'):
            state='Oczekuje na OCR' if job['state']=='queued' else 'Trwa odczyt OCR'
            body=(f"<div class='card'><h1>{state}</h1><p>Plik został zapisany. Analiza działa poza żądaniem HTTP. Ta strona odświeży się automatycznie.</p>"
                  "<p><a class='btn' href='/inbox'>Wróć do skrzynki</a></p></div><script>setTimeout(()=>location.reload(),3500)</script>")
            return self.send_html(a.layout('Analiza wpływu',body,'inbox'))
        if job and job['state']=='error':
            body=("<div class='card'><h1>Nie udało się przeanalizować pisma</h1>"
                  "<p>Oryginalny plik jest bezpiecznie zapisany i nie trafił do sprawy."
                  " Możesz ponowić analizę albo odrzucić wpływ.</p>"
                  f"<p class='small muted'>{escape(job['error'])}</p>"
                  f"<form method='post' action='/inbox/{item_id}/retry'><button class='btn primary'>Ponów OCR</button></form>"
                  "<a class='btn' href='/inbox'>Wróć</a></div>")
            return self.send_html(a.layout('Błąd OCR',body,'inbox'),500)
        if row['status'] != 'pending':''',
        'inbox processing UI')
    inbox=change_function(inbox,'inbox_review',review,'InboxMixin')
    approve=source_function(inbox,'inbox_approve','InboxMixin')
    approve=replace_once(approve,
        "            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()",
        "            row = con.execute('SELECT * FROM inbox_items WHERE id=?', (item_id,)).fetchone()\n            job = job_state(con,item_id)",
        'inbox approve state')
    approve=replace_once(approve,
        "        if row['status'] == 'approved' and row['document_id']:",
        "        if job and job['state'] != 'ready':\n            return self._inbox_error('Analiza pliku nie została jeszcze zakończona.',409,f'/inbox/{item_id}')\n        if row['status'] == 'approved' and row['document_id']:",
        'block unprocessed approve')
    inbox=change_function(inbox,'inbox_approve',approve,'InboxMixin')
    inbox=replace_once(inbox,
        '    def inbox_discard(self, item_id: int, fields):',
'''    def inbox_retry(self,item_id:int,fields):
        a=self._app()
        if not retry_job(a,item_id):
            return self._inbox_error('Nie można ponowić tej analizy.',409,f'/inbox/{item_id}')
        return self.redirect(f'/inbox/{item_id}')

    def inbox_discard(self, item_id: int, fields):''',
        'retry method')
    # Keep the file acceptance policy but clarify which formats can be read.
    inbox=replace_once(inbox,
        'Analiza działa lokalnie. Data końcowa terminu, adresat zobowiązania i przypisanie sprawy zawsze wymagają ręcznej kontroli.',
        'Odczyt tekstu obsługuje PDF, DOCX, ODT, XLSX, ODS, PPTX, EML, pliki tekstowe i część obrazów. Stare DOC, ZIP oraz audio/wideo można dołączyć, ale nie są transkrybowane. Propozycje i terminy zawsze wymagają ręcznej kontroli.',
        'formats UI')
    src['rk_inbox.py']=inbox

    # Migrate extraction of additional file formats with safe size limits.
    ocr=src['rk_domains/documents/ocr.py']
    ocr=replace_once(ocr,
        'import zipfile\nimport xml.etree.ElementTree as ET\n',
        'import zipfile\nimport time\nimport xml.etree.ElementTree as ET\nfrom rk_domains.documents.format_support import extract_extra_text,xml_member\n',
        'ocr parser imports')
    ocr=replace_once(ocr,
        "    max_pages=max(1,int(os.getenv('RK_OCR_MAX_PAGES','300') or 300))",
        "    max_pages=max(1,min(60,int(os.getenv('RK_OCR_MAX_PAGES','35') or 35)))",
        'ocr page bound')
    ocr=replace_once(ocr,
        "            with zipfile.ZipFile(io.BytesIO(data),'r') as z:\n                xml=z.read('word/document.xml')\n            root=ET.fromstring(xml); texts=[]",
        "            root=xml_member(data,'word/document.xml'); texts=[]",
        'DOCX ZIP decompression bound')
    ocr=replace_once(ocr,
        "    try:\n        if ext=='.docx':",
        "    try:\n        if ext in {'.odt','.ods','.pptx','.eml'}:\n            return extract_extra_text(filename,data)\n        if ext=='.docx':",
        'ocr additional supported formats')
    ocr=replace_once(ocr,
        "            total=min(len(doc),max_pages)\n            for i in range(total):",
        "            total=min(len(doc),max_pages)\n            started=time.monotonic()\n            for i in range(total):\n                if time.monotonic()-started>180:\n                    out.append('[Limit czasu OCR 180 sekund; pozostałe strony wymagają ręcznej kontroli]')\n                    break",
        'ocr total runtime')
    ocr=replace_once(ocr,
        "                page=doc.load_page(i)\n                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)",
        "                page=doc.load_page(i)\n                if page.rect.width*page.rect.height*(dpi/72)**2>18_000_000:\n                    out.append(existing or '[Strona przekracza limit rozmiaru obrazu do OCR]')\n                    continue\n                pix=page.get_pixmap(matrix=fitz.Matrix(dpi/72,dpi/72),alpha=False)",
        'OCR pixel bound')
    ocr=replace_once(ocr,
        "    return ('',0,'nieobslugiwany_format','')",
        "    return ('',0,'bez_odczytu_formatu','')",
        'unsupported status')
    src['rk_domains/documents/ocr.py']=ocr

    # Sync: explicit schema version and journal-based rollback of the entire state.
    sync=src['rk_sync.py']
    sync=replace_once(sync,'SCHEMA_VERSION = 240','SCHEMA_VERSION = CURRENT_SCHEMA_VERSION','sync schema')
    sync=replace_once(sync,'from rk_paths import installed_data_dir, resolve_runtime_paths\n',
'''from rk_paths import installed_data_dir, resolve_runtime_paths
from rk_core.schema_version import SCHEMA_VERSION as CURRENT_SCHEMA_VERSION
from rk_core.sync_atomic import commit_staged,pending_sync_journal,SyncRecoveryRequired
''','sync imports')
    sync=change_function(sync,'copy_full_state',
'''def copy_full_state(source: Path, destination: Path, label: str) -> Path:
    """Replace the full state with automatic rollback on caught errors."""
    source=_norm_path(source);destination=_norm_path(destination)
    if source==destination:raise SyncError('Źródło i cel to ten sam katalog.')
    if active_lock(source) or active_lock(destination):
        raise SyncError('Zamknij obie instancje RK KANCELARIA przed synchronizacją.')
    if pending_sync_journal(destination):
        raise SyncError('Niedokończona synchronizacja. Najpierw przywróć kopię, nie nadpisuj danych.')
    src_db=source/'sprawnik.sqlite3'
    if not src_db.is_file():raise SyncError('Brak źródłowej bazy SQLite: '+str(src_db))
    ok,why=_sqlite_integrity(src_db)
    if not ok:raise SyncError('Baza źródłowa jest uszkodzona: '+str(why))
    conn=sqlite3.connect(src_db)
    try:src_ver=int(conn.execute('PRAGMA user_version').fetchone()[0])
    finally:conn.close()
    if src_ver>SCHEMA_VERSION:raise SyncError(f'Źródłowy schemat {src_ver} jest nowszy niż {SCHEMA_VERSION}.')
    destination.mkdir(parents=True,exist_ok=True)
    backup=backup_destination(destination,label)
    settings=_local_settings(destination/'sprawnik.sqlite3')
    stage=destination/('.sync_stage_'+uuid.uuid4().hex)
    stage.mkdir(parents=True,exist_ok=False)
    try:
        stage_db=stage/'sprawnik.sqlite3'
        _sqlite_backup(src_db,stage_db)
        _apply_local_settings(stage_db,settings)
        for dirname in MANAGED_DIRS:_copytree(source/dirname,stage/dirname)
        commit_staged(destination,backup,stage_db,stage,MANAGED_DIRS,_replace_dir,_sqlite_integrity)
        return backup
    except SyncRecoveryRequired as exc:raise SyncError(str(exc)) from exc
    finally:shutil.rmtree(stage,ignore_errors=True)
''')
    src['rk_sync.py']=sync

    # Cloud client rejects remote HTTP; server refuses to persist plaintext ZIPs.
    cloud=src['rk_cloud.py']
    cloud=replace_once(cloud,'import urllib.request\n',
        'import urllib.request\nfrom rk_core.cloud_security import validate_cloud_url,CloudCryptoError\n',
        'cloud HTTP client import')
    cloud=change_function(cloud,'_base',
'''def _base(url: str) -> str:
    try:return validate_cloud_url(url)
    except CloudCryptoError as exc:raise CloudError(str(exc)) from exc
''')
    cloud=replace_once(cloud,"'Content-Type':'application/zip'","'Content-Type':'application/octet-stream'",'Cloud encrypted upload MIME')
    cloud=replace_once(cloud,"{'Accept':'application/zip'}","{'Accept':'application/octet-stream'}",'Cloud encrypted download Accept')
    src['rk_cloud.py']=cloud
    cs=src['rk_cloud_server.py']
    cs=replace_once(cs,"if payload[:2]!=b'PK': return self.json(400,{'error':'Snapshot nie jest archiwum ZIP.'})",
                    "if not payload.startswith(b'RKCLD2'): return self.json(400,{'error':'Cloud wymaga zaszyfrowanego snapshotu RKCLD2.'})",
                    'cloud server encryption only')
    cs=replace_once(cs,"self.send_header('Content-Type','application/zip')",
                       "self.send_header('Content-Type','application/octet-stream')",
                       'Cloud encrypted payload mime')
    src['rk_cloud_server.py']=cs

    # Prevent stale UI JS in PWA static cache.
    sw=src['assets/service-worker.js']
    sw=replace_once(sw,"const CACHE='rk-kancelaria-static-0.3.0-dev4';",
                    "const CACHE='rk-kancelaria-static-0.4.0-dev2';",'SW version')
    sw=replace_once(sw,"  '/assets/rk_app.js',",
                    "  '/assets/rk_app.js',\n  '/assets/rk_csrf.js',",'SW CSRF script')
    src['assets/service-worker.js']=sw
    # Test architektury może zostać wgrany przed instalatorem dev2.
    # Wtedy ma już nowy warunek wersji; nie próbuj nadpisywać nieistniejącej kotwicy.
    # Jednocześnie odrzucaj nieznaną treść zamiast pomijać walidację.
    arch=src['TEST_ARCHITEKTURA_040.py']
    old_arch = "self.assertIn('VERSION = \"0.4.0-dev1\"',app)"
    dev2_arch = "self.assertIn('VERSION = \"0.4.0-dev2\"',app)"
    compatible_arch = "self.assertTrue('VERSION = \"0.4.0-dev1\"' in app or 'VERSION = \"0.4.0-dev2\"' in app)"
    if arch.count(old_arch)==1:
        arch=replace_once(arch,old_arch,compatible_arch,'old architecture test version tolerance')
    elif arch.count(dev2_arch)==1 or arch.count(compatible_arch)==1:
        # Test jest już przystosowany do dev2; zostaw jego treść bez zmian.
        pass
    else:
        raise RuntimeError('Nieznana wersja TEST_ARCHITEKTURA_040.py. Nic nie zmieniono.')
    src['TEST_ARCHITEKTURA_040.py']=arch
    src['RAPORT_JAKOSCI_040.py']=src['RAPORT_JAKOSCI_040.py'].replace("'version':'0.4.0-dev1'","'version':'0.4.0-dev2'")

    all_updates={**src,**created}
    # Added recovery CLI is standalone and requires a Python source checkout.
    all_updates['ODZYSKAJ_SYNCHRONIZACJE_040.py']=_decode_payload()['ODZYSKAJ_SYNCHRONIZACJE_040.py']
    # Safe preflight: verify syntax of every changed Python file before writes.
    for name,content in all_updates.items():
        if name.endswith('.py'):compile(content,name,'exec')
    return {name:content for name,content in all_updates.items()
            if not (repo/name).is_file() or (repo/name).read_text(encoding='utf-8')!=content}


def apply(repo: Path,dry_run: bool=False) -> str:
    repo=repo.resolve()
    changes=build_changes(repo)
    if not changes:return 'RK KANCELARIA 0.4.0-dev2 jest już zainstalowana. Bez zmian.'
    if dry_run:return f'DRY RUN OK: {len(changes)} plików; katalog Data bez zmian.'
    backup=repo/'.rk_backup_before_040_dev2'
    if backup.exists():raise RuntimeError('Kopia kodu 0.4-dev2 już istnieje, nie nadpisano jej.')
    originals={name:(repo/name).read_bytes() if (repo/name).is_file() else None for name in changes}
    backup.mkdir(parents=True)
    for name,raw in originals.items():
        if raw is None:continue
        dst=backup/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw)
    (backup/'manifest.json').write_text(json.dumps({n:{'existed':data is not None,
        'sha256':hashlib.sha256(data).hexdigest() if data is not None else None} for n,data in originals.items()},indent=2),encoding='utf-8')
    installed=[]
    try:
        for name,content in changes.items():
            dest=repo/name;dest.parent.mkdir(parents=True,exist_ok=True)
            fd,tmp=tempfile.mkstemp(prefix='.rkdev2_',dir=dest.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
                    f.write(content);f.flush();os.fsync(f.fileno())
                os.replace(tmp,dest);installed.append(name)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
    except Exception:
        for name in reversed(installed):
            raw=originals[name]
            if raw is None:(repo/name).unlink(missing_ok=True)
            else:(repo/name).write_bytes(raw)
        raise
    return f'Zainstalowano 0.4.0-dev2: {len(changes)} zmienionych plików źródłowych; Data nietknięty.'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('repo',nargs='?',default='.')
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args(argv)
    print(apply(Path(a.repo),a.dry_run))
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('BŁĄD 0.4.0-dev2:',str(exc),file=sys.stderr)
        raise SystemExit(2)
